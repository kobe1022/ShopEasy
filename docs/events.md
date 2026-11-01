# Events (Message Broker)

Alle Statusänderungen laufen als Nachricht über den Topic-Exchange `retouren.status`.
Der Routing-Key ist der `event_type`. Die Payload-Felder sind in
`src/shopeasy/shared/events.py` als Pydantic-Modelle festgelegt; dieses Dokument
beschreibt sie. Änderungen bitte im Team absprechen, alle Services hängen daran.

## Umschlag

```json
{
  "event_id": "7f3c1e2a-...",
  "event_type": "ware.eingegangen",
  "retouren_id": "RET-2026-000123",
  "timestamp": "2026-11-02T09:41:12Z",
  "source": "warehouse-grpc",
  "schema_version": 1,
  "payload": { }
}
```

| Feld             | Bedeutung                                                      |
| ---------------- | -------------------------------------------------------------- |
| `event_id`       | UUID, Grundlage der Idempotenz (ein Event wird je Queue einmal verarbeitet) |
| `event_type`     | Routing-Key, siehe unten                                       |
| `retouren_id`    | Fall-ID (`RET-JJJJ-NNNNNN`), im Event-Log die `case_id`        |
| `timestamp`      | UTC, Format `JJJJ-MM-TTThh:mm:ssZ`                             |
| `source`         | Absender, z. B. `retouren-service`, `warehouse-grpc`           |
| `schema_version` | derzeit 1                                                      |
| `payload`        | Felder je Event-Typ, siehe unten                               |

Alle Zeitangaben im Payload (z. B. `pruef_frist`) haben dasselbe Format wie `timestamp`.

Sender bauen Events mit `build_event(...)`, das den Payload gegen das Modell prüft.
Consumer lesen ihn mit `parse_payload(event)`. Passt ein Payload nicht zum Event-Typ,
lehnt der Event-Log-Consumer die Nachricht ab und sie landet in der Dead-Letter-Queue
`retouren.dlq`.

## Event-Typen

| Routing-Key                | Soll-BPMN (Status-Ereignis)       | Absender (Sprint 2)        | Payload                                                                                          |
| -------------------------- | --------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------ |
| `retoure.registriert`      | Status: Retoure registriert       | Retouren-Service           | `kanal`, `externe_id`, `bestell_nr`, `kunde_email`, `grund_text`, `artikel[]`                    |
| `retoure.abgelehnt`        | Status: Retoure abgelehnt         | Sprint 4 (Workflow)        | `grund`                                                                                          |
| `label.bereitgestellt`     | Status: Label bereitgestellt      | Sprint 4 (Workflow)        | `tracking_nr`, `versanddienstleister`                                                            |
| `ruecksendung.unterwegs`   | Status: Rücksendung unterwegs     | Sprint 4 (Workflow)        | `tracking_nr`                                                                                    |
| `ware.eingegangen`         | Status: Ware eingegangen          | gRPC-Wareneingang          | `scanner_id`, `pruef_frist`, `already_cancelled` (Standard `false`)                              |
| `pruefung.abgeschlossen`   | Prüfergebnis im WMS gespeichert   | gRPC-Wareneingang          | `condition`, `inspector`, `note` (Standard leer), `photo_refs` (Standard leer)                   |
| `retoure.angenommen`       | Status: Retoure angenommen        | Sprint 4 (Workflow)        | `entschieden_durch` (z. B. `dmn` oder Kürzel der Sachbearbeitung)                                |
| `erstattung.abgeschlossen` | Status: Erstattung abgeschlossen  | Sprint 4 (Workflow)        | `betrag` (≥ 0), `art` (`ZAHLUNG` oder `GUTSCHEIN`)                                               |
| `retoure.storniert`        | Status: Retoure storniert         | Sprint 4 (Workflow)        | `grund`                                                                                          |

### Wertebereiche

- `kanal`: `AMAZON`, `ZALANDO`, `WEBSHOP`, `EMAIL`
- `externe_id`: ID der Meldung beim Marktplatz, sonst `null` (Webshop, E-Mail)
- `artikel[]`: Liste aus `{ "sku": "PULLI-BLAU-M", "menge": 1 }`
- `condition`: `NEUWERTIG`, `GETRAGEN`, `BESCHAEDIGT`, `UNVOLLSTAENDIG`, `FALSCHER_ARTIKEL`
  (gleiche Namen wie `Condition` in `warehouse.proto`, ohne `CONDITION_UNSPECIFIED`)
- `photo_refs`: Liste von Verweisen auf Fotos bei Schäden oder unklaren Fällen
- `pruef_frist`: 24 Stunden nach dem Wareneingang

### Beispiele

`retoure.registriert`:

```json
{
  "kanal": "AMAZON",
  "externe_id": "AMZ-RET-001001",
  "bestell_nr": "ORD-100234",
  "kunde_email": "kundin@example.com",
  "grund_text": "Zu klein: Faellt klein aus",
  "artikel": [{ "sku": "PULLI-BLAU-M", "menge": 1 }]
}
```

`ware.eingegangen`:

```json
{
  "scanner_id": "LAGER-03",
  "pruef_frist": "2026-11-03T09:41:12Z",
  "already_cancelled": false
}
```

`pruefung.abgeschlossen`:

```json
{
  "condition": "BESCHAEDIGT",
  "inspector": "lager-01",
  "note": "Reissverschluss defekt",
  "photo_refs": ["foto-001.jpg"]
}
```

## Queues

| Queue        | Routing-Keys                                   | Consumer                       |
| ------------ | ---------------------------------------------- | ------------------------------ |
| `kundeninfo` | alle außer `pruefung.abgeschlossen`            | `consumers/kundeninfo.py`      |
| `eventlog`   | `#` (alle)                                     | `consumers/eventlog.py`        |
| `retouren.dlq` | nicht verarbeitbare Nachrichten              | manuell prüfen                 |
