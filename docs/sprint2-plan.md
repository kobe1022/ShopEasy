# Sprint 2: Integrationstechniken (Kurzfassung des Vorgehenskonzepts)

Abgabe: 03.11.2026, 11:30 Uhr in ILIAS (GitHub-Link). Jede Komponente gehört zu einem
Element im Soll-BPMN und wird in Sprint 4 von Camunda genutzt.

## 1. REST: Mock-Marktplatz und Retouren-Service (Nikky)

Soll-BPMN: Start "Marktplatz-Meldung eingegangen (REST)", Task "Retourenvorgang anlegen,
Retouren-ID vergeben". Schwachstellen S1, S4.

Mock-Marktplatz (Port 8001), Amazon und Zalando mit **unterschiedlichen JSON-Formaten**
(Feldnamen, Datumsformate, Grund-Codes):

| Methode | Endpunkt                              | Zweck                         |
| ------- | ------------------------------------- | ----------------------------- |
| GET     | `/amazon/returns?status=new`          | neue Amazon-Meldungen         |
| GET     | `/zalando/returns?status=new`         | neue Zalando-Meldungen        |
| GET     | `/{marketplace}/returns/{id}`         | einzelne Meldung              |
| POST    | `/{marketplace}/returns/{id}/ack`     | Meldung quittieren            |
| POST    | `/{marketplace}/returns`              | Testfall erzeugen (Demo)      |

Retouren-Service (Port 8002): Meldungen abholen (Polling mit Quittierung), Webshop per
`POST /returns`, normalisieren, Retourenvorgang anlegen, Retouren-ID vergeben
(`RET-2026-000123`), Dublettenprüfung über die externe Marktplatz-ID (409 Conflict),
Event `retoure.registriert` publizieren, `GET /returns/{retouren_id}` (Status, Historie).
Pydantic-Validierung, Statuscodes 200/201/404/409/422, OpenAPI unter `/docs`.

Testdaten: Normalfall, Rückgabefrist überschritten, doppelte Meldung, unklarer
Freitext-Retourengrund (für den KI-Agenten in Sprint 5), Kunde mit auffällig vielen
Retouren.

## 2. gRPC: Wareneingang und Zustandserfassung (Benjamin)

Soll-BPMN: "Wareneingang registrieren, Prüffrist setzen", Gateway "Retoure bereits
storniert?", "Ware prüfen und Zustand erfassen (Scanner-App)", "Prüfergebnis im WMS
speichern". Schwachstellen S3, S4, S6.

Definition in `proto/shopeasy/warehouse/v1/warehouse.proto`. Server = WMS (Port 50051),
Scanner-CLI = Scanner-App im Lager. Fehlerbehandlung über gRPC-Statuscodes:
`NOT_FOUND` (unbekannte Retouren-ID), `FAILED_PRECONDITION` (Prüfung vor Wareneingang),
`ALREADY_EXISTS` (doppelter Scan), `INVALID_ARGUMENT` (Zustand fehlt). Nach Erfolg werden
`ware.eingegangen` bzw. `pruefung.abgeschlossen` publiziert.

## 3. Messaging: RabbitMQ und Consumer (Muhammed)

Soll-BPMN: alle Zwischenereignisse "Status: ..." und die Event-Log-Anmerkung.
Schwachstellen S2, S4.

Topic-Exchange `retouren.status`, Routing-Keys siehe `shared/events.py`. Consumer:

- **Kundeninfo**: simulierte Status-Mail im Log bei kundenrelevanten Events (KPI K14).
- **Event-Log**: jedes Event als Zeile (Fall-ID, Aktivität, Zeitstempel) in CSV oder DB;
  Datenbasis für Process Mining in Sprint 3.
- Später (Sprint 4): Camunda-Bridge.

Robustheit: durable Queues, persistente Nachrichten, manuelles Ack nach erfolgreicher
Verarbeitung, Dead-Letter-Queue, idempotente Consumer über `event_id`.

## 4. Demo fürs Review (gemeinsam)

`scripts/demo.py`: Zalando-Retoure erzeugen, Retouren-Service holt sie ab, Scanner meldet
Wareneingang, Scanner erfasst Zustand. Verlauf im RabbitMQ-UI, Event-Log und in den
Status-Mails sichtbar. Fehlerfälle: Dublette (409), unbekannte Retouren-ID (`NOT_FOUND`),
fehlerhafte Nachricht in der Dead-Letter-Queue.

## 5. Abgabe

README mit Startanleitung, Architekturbild, Endpunkt- und Proto-Übersicht, Abschnitt
"Wo im Soll-BPMN wird das genutzt?" und Dokumentation der KI-Nutzung.

Offene Frage an den Dozenten für Sprint 4: Camunda 7 oder 8? (gRPC braucht in beiden
Fällen einen kleinen Worker.)
