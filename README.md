# ShopEasy

Retourenabwicklung der ShopEasy GmbH (Projekt "Digitalisierung eines Geschäftsprozesses",
WS 26, Prof. Dr. Andreas Heberle). Dieses Repository enthält die Bausteine von
**Sprint 2 (Integrationstechniken)**:

| Baustein                                            | Umsetzung                                                 | Code                                                       |
| --------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| Mock-REST-API für Retourenmeldungen                 | FastAPI, simuliert Amazon und Zalando (zwei Formate)      | `src/shopeasy/marketplace_mock/`                           |
| gRPC-Service für Wareneingang und Zustandserfassung | grpcio, Definition in `proto/`                            | `src/shopeasy/warehouse_grpc/`                             |
| Status-Updates über einen Message Broker            | RabbitMQ, Topic-Exchange `retouren.status`, zwei Consumer | `src/shopeasy/shared/broker.py`, `src/shopeasy/consumers/` |

Dazu gehören ein **Retouren-Service** (holt Marktplatz-Meldungen ab, wandelt sie in ein
einheitliches Modell um und legt sie in der Retourenakte an, `src/shopeasy/return_service/`)
und eine **Scanner-CLI** als gRPC-Client (`src/shopeasy/clients/`).

## Starten

Voraussetzung: Docker. Für Demo, Scanner-CLI und Tests zusätzlich _uv_ und Python 3.15
(`uv sync --all-groups`).

```shell
docker compose up -d --build     # RabbitMQ und alle Dienste
uv run python scripts/demo.py    # führt einen Retourenfall und die Fehlerfälle vor
docker compose down -v           # beenden und Daten löschen
```

| Was                 | Wo                                       |
| ------------------- | ---------------------------------------- |
| Mock-Marktplatz     | <http://127.0.0.1:8001/docs>             |
| Retouren-Service    | <http://127.0.0.1:8002/docs>             |
| gRPC-Wareneingang   | 127.0.0.1:50051                          |
| RabbitMQ-Oberfläche | <http://127.0.0.1:15672> (guest / guest) |
| Event-Log (CSV)     | `data/eventlog.csv`                      |
| Status-Mails (Log)  | `docker compose logs kundeninfo`         |

Ohne Docker für die Dienste: RabbitMQ mit `docker compose up -d rabbitmq` starten, dann
im Projektordner (alle Dienste teilen sich `data/retourenakte.db`):

```shell
uv run python -m shopeasy.marketplace_mock
uv run python -m shopeasy.return_service
uv run python -m shopeasy.warehouse_grpc
uv run python -m shopeasy.consumers.eventlog
uv run python -m shopeasy.consumers.kundeninfo
```

Einstellungen per Umgebungsvariable (Standardwerte in `src/shopeasy/shared/config.py`):
`RABBITMQ_URL`, `DB_PATH`, `EVENTLOG_PATH`, `IDEMPOTENZ_DB`, `MARKETPLACE_MOCK_URL`,
`WAREHOUSE_GRPC_ADDRESS`.

## Architektur

```text
Mock-Marktplatz --REST--> Retouren-Service --+
 (Amazon, Zalando)        (Retourenakte)     |  Status-Events
Scanner-CLI --gRPC--> Wareneingangs-Service -+
                                             v
                          RabbitMQ, Exchange retouren.status (Topic)
                                   |                         |
                         Warteschlange eventlog   Warteschlange kundeninfo
                       -> data/eventlog.csv      -> simulierte Status-Mail
```

Die Retourenakte (SQLite) ist die gemeinsame Datenbasis: der Retouren-Service legt
Vorgänge an, der gRPC-Service liest sie (unbekannte oder stornierte Retoure) und
ergänzt Wareneingang und Prüfergebnis.

## Schnittstellen

**Mock-Marktplatz** (Port 8001, `marketplace` = `amazon` oder `zalando`, je eigenes Format):

| Aufruf                                  | Zweck                                            |
| --------------------------------------- | ------------------------------------------------ |
| `GET /{marketplace}/returns?status=new` | Meldungen abrufen (`new`, `acknowledged`, `all`) |
| `GET /{marketplace}/returns/{id}`       | einzelne Meldung (404 wenn unbekannt)            |
| `POST /{marketplace}/returns`           | Testmeldung anlegen (201)                        |
| `POST /{marketplace}/returns/{id}/ack`  | Meldung als übernommen quittieren                |

**Retouren-Service** (Port 8002):

| Aufruf                                    | Zweck                                                               |
| ----------------------------------------- | ------------------------------------------------------------------- |
| `POST /returns`                           | Webshop-Anmeldung (201, bei ungültigen Angaben 422)                 |
| `POST /returns/poll`                      | neue Meldungen beider Marktplätze abholen, anlegen und quittieren   |
| `POST /returns/marketplace/{marketplace}` | Meldung per Webhook (201, doppelt: 409 mit bestehender Nummer, 422) |
| `GET /returns/{retouren_id}`              | Status und Verlauf (404 wenn unbekannt)                             |

Doppelte Meldungen erkennt der Service an der Marktplatz-ID. Meldungen mit ungültigem Inhalt
(z. B. unbekannte EAN) werden nicht angelegt und beim Polling nicht quittiert.

**gRPC** (`shopeasy.warehouse.v1.WarehouseService`, Port 50051, Definition `proto/shopeasy/warehouse/v1/warehouse.proto`):

| Methode                | Zweck und Fehlercodes                                                                                                                                                                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RegisterGoodsReceipt` | Wareneingang erfassen, Prüffrist 24 h; meldet `already_cancelled`. `NOT_FOUND` (unbekannte Retoure), `ALREADY_EXISTS` (doppelter Scan), `INVALID_ARGUMENT`                                                                 |
| `RecordInspection`     | Zustand erfassen (neuwertig, getragen, beschädigt, unvollständig, falscher Artikel). `NOT_FOUND`, `FAILED_PRECONDITION` (kein Wareneingang oder storniert), `ALREADY_EXISTS`, `INVALID_ARGUMENT` (u. a. Schaden ohne Foto) |
| `GetInspection`        | Prüfergebnis abfragen, `NOT_FOUND` wenn es keines gibt                                                                                                                                                                     |

Scanner-App (der Server muss laufen):

```shell
uv run python -m shopeasy.clients.scanner_cli receive RET-2026-000001
uv run python -m shopeasy.clients.scanner_cli inspect RET-2026-000001 BESCHAEDIGT --photo foto-001.jpg
uv run python -m shopeasy.clients.scanner_cli get RET-2026-000001
```

**Status-Meldungen** (RabbitMQ): Routing-Key = Event-Typ (`retoure.registriert`,
`ware.eingegangen`, `pruefung.abgeschlossen` u. a., insgesamt neun). Aufbau und Felder jedes
Events stehen in [docs/events.md](docs/events.md). Gesendet werden bisher
`retoure.registriert` (Retouren-Service) sowie `ware.eingegangen` und
`pruefung.abgeschlossen` (gRPC); die übrigen folgen mit dem Workflow in Sprint 4.
Nachrichten sind persistent, werden erst nach erfolgreicher Verarbeitung bestätigt und über
die `event_id` höchstens einmal je Warteschlange verarbeitet. Nicht verarbeitbare Nachrichten landen
in der Fehler-Warteschlange `retouren.dlq` (englisch Dead-Letter-Queue).

## Wo im Soll-BPMN wird das genutzt?

| Komponente                   | Element im Soll-BPMN                                                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Mock-REST + Retouren-Service | Start "Marktplatz-Meldung eingegangen (REST)", "Retourenvorgang anlegen, Retouren-ID vergeben"                                                   |
| gRPC-Wareneingang            | "Wareneingang registrieren, Prüffrist setzen", "Retoure bereits storniert?", "Ware prüfen und Zustand erfassen", "Prüfergebnis im WMS speichern" |
| Messaging                    | alle Zwischenereignisse "Status: ...", Event-Log, Benachrichtigung der Kund:innen                                                                |

## Tests

```shell
uv run pytest
uv run ruff check src tests scripts
```

Die Tests laufen ohne RabbitMQ. Den Ablauf mit allen Diensten zeigt `scripts/demo.py`.

## Grenzen

- Fällt RabbitMQ länger aus, geht das zugehörige Status-Event verloren (es wird nur
  protokolliert); die Retoure bleibt angelegt.
- Alle Dienste brauchen dieselbe Retourenakte. In Docker gibt es dafür ein gemeinsames Volume,
  lokal müssen alle aus dem Projektordner starten.
- Der Kundeninfo-Dienst schreibt bisher die Mails nur ins Log.

## Zuständigkeiten

| Person   | Teil                                          | Ordner                                                                                             |
| -------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Niklas   | REST: Mock-Marktplatz, Retouren-Service       | `src/shopeasy/marketplace_mock/`, `src/shopeasy/return_service/`                                   |
| Benjamin | gRPC: Wareneingang, Scanner-CLI, Docker, Demo | `proto/`, `src/shopeasy/warehouse_grpc/`, `src/shopeasy/clients/`, `scripts/demo.py`, `Dockerfile` |
| Muhammed | Messaging: Broker-Helper, Consumer            | `src/shopeasy/shared/broker.py`, `src/shopeasy/consumers/`                                         |

Gemeinsam: Event-Schema (`src/shopeasy/shared/events.py`), Retourenakte
(`src/shopeasy/shared/retourenakte.py`). Der Plan für Sprint 2 steht in [docs/sprint2-plan.md](docs/sprint2-plan.md).

## KI-Nutzung

Ein KI-Assistent (Claude) wurde eingesetzt. Bei diesen Teilen wurden wir durch die KI unterstützt:

| Person   | Teil                                    | Wobei die KI geholfen hat          |
| -------- | --------------------------------------- | ---------------------------------- |
| Benjamin | gRPC-Service, Scanner-CLI, Docker, Demo | Code, Tests, Dokumentation, Gerüst |
| Niklas   | Mock-Marktplatz, Retouren-Service       | Code, Tests, Fehlersuche           |
| Muhammed | Broker-Helper, Consumer                 | Code, Tests, Mailtexte             |
