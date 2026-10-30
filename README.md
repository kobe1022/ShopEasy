# ShopEasy

Digitalisierung der Retourenabwicklung der ShopEasy GmbH (Projekt "Digitalisierung eines
Geschäftsprozesses", WS 26, Prof. Dr. Andreas Heberle). Dieses Repository enthält die
Bausteine aus Sprint 2: Mock-REST-API, gRPC-Service und Status-Updates über RabbitMQ.

## Autoren und Zuständigkeiten

| Person   | Teil                                    | Ordner                                                                           |
| -------- | --------------------------------------- | -------------------------------------------------------------------------------- |
| Nikky    | REST: Mock-Marktplatz, Retouren-Service | `src/shopeasy/marketplace_mock/`, `src/shopeasy/return_service/`                 |
| Benjamin | gRPC: Wareneingang, Scanner-CLI         | `proto/`, `src/shopeasy/warehouse_grpc/`, `src/shopeasy/clients/`                |
| Muhammed | Messaging: RabbitMQ, Consumer           | `src/shopeasy/shared/broker.py`, `src/shopeasy/consumers/`, `docker-compose.yml` |

Gemeinsam: Event-Schema (`src/shopeasy/shared/events.py`), `.proto`, Demo-Skript, README.
Änderungen an diesen Schnittstellen bitte vorher absprechen. Jede Person arbeitet auf
einem eigenen Branch und mergt per Pull Request nach `main`.

## Architektur

```text
Mock-Marktplatz (REST, 8001) --> Retouren-Service (REST, 8002) --+
                                                                 v
Scanner-CLI --> Wareneingangs-Service (gRPC, 50051) --> RabbitMQ (Topic-Exchange
                                                        retouren.status)
                                                          |           |
                                                    Kundeninfo   Event-Log
                                                    (Status-Mail) (CSV/DB, Sprint 3)
```

Retourenakte: SQLite (`data/retourenakte.db`, Pfad über `DB_PATH`).

## Einrichtung

Voraussetzungen: _uv_, Python `>=3.15` und _Docker_.

```shell
uv sync --all-groups        # Abhängigkeiten installieren
docker compose up -d        # RabbitMQ, Oberfläche: http://localhost:15672 (guest/guest)
```

## Starten (je Service ein Terminal)

```shell
uv run python -m shopeasy.marketplace_mock       # http://localhost:8001/docs
uv run python -m shopeasy.return_service         # http://localhost:8002/docs
uv run python -m shopeasy.warehouse_grpc         # localhost:50051
uv run python -m shopeasy.consumers.kundeninfo
uv run python -m shopeasy.consumers.eventlog
uv run python -m shopeasy.clients.scanner_cli --help
```

Tests und Codeanalyse:

```shell
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
```

gRPC-Code neu erzeugen, nachdem sich die `.proto`-Datei geändert hat (das Ergebnis liegt
im Repository, damit niemand `protoc` einrichten muss):

```shell
uv run python -m grpc_tools.protoc -I proto --python_out=src --grpc_python_out=src --pyi_out=src proto/shopeasy/warehouse/v1/warehouse.proto
```

## Status

Das Grundgerüst steht: alle Services starten, die REST-Endpunkte und gRPC-Methoden
antworten mit "noch nicht implementiert" (501 bzw. `UNIMPLEMENTED`), die Consumer loggen
jedes Event. Publish-Helper, Topologie (Exchange, Queues, Dead-Letter-Queue) und
Event-Schema sind fertig. Die Aufgaben stehen als `TODO` in den Modulen, Details in
[docs/sprint2-plan.md](docs/sprint2-plan.md).

## Wo im Soll-BPMN wird das genutzt?

| Komponente                   | Element im Soll-BPMN                                                                                                                            |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Mock-REST + Retouren-Service | Start "Marktplatz-Meldung eingegangen (REST)", "Retourenvorgang anlegen, Retouren-ID vergeben"                                                  |
| gRPC-Wareneingang            | "Wareneingang registrieren, Prüffrist setzen", "Retoure bereits storniert?", "Ware prüfen und Zustand erfassen", "Prüfergebnis im WMS speichern" |
| Messaging                    | alle Zwischenereignisse "Status: ...", Event-Log                                                                                                |

## KI-Nutzung

Das Grundgerüst (Projektstruktur, Event-Schema, Broker-Helper, Platzhalter) wurde mit
Unterstützung eines KI-Assistenten erstellt. Die inhaltliche
Umsetzung der Komponenten dokumentiert jede Person hier für ihren Teil.
