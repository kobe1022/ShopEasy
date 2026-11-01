"""gRPC-Server in der Rolle des WMS. Zustaendig: Benjamin.

Wareneingang und Zustandserfassung (siehe docs/sprint2-plan.md, Abschnitt 4).
Die Retourenakte (`shopeasy.shared.retourenakte`) bleibt die Datenbasis, die
Lagerdaten liegen in `lager.py`.

Nach jedem erfolgreichen Aufruf geht ein Status-Event an den Message Broker:
`ware.eingegangen` beim Wareneingang und `pruefung.abgeschlossen` bei der
Zustandserfassung (Felder siehe docs/events.md).
"""

from concurrent import futures
from datetime import UTC, datetime

import grpc
from loguru import logger
from pika.exceptions import AMQPError

from shopeasy.shared import broker, retourenakte
from shopeasy.shared.events import (
    Event,
    EventType,
    PruefungAbgeschlossenPayload,
    WareEingegangenPayload,
    build_event,
)
from shopeasy.shared.models import RetourenStatus, Zustand
from shopeasy.warehouse.v1 import warehouse_pb2, warehouse_pb2_grpc
from shopeasy.warehouse_grpc import lager

QUELLE = "warehouse-grpc"


def _melden(event: Event) -> None:
    """Sendet das Status-Event an den Message Broker.

    Ist RabbitMQ nicht erreichbar, bleibt die Erfassung im Lager trotzdem
    gespeichert (das Lager darf nicht stehen); das Event wird nur protokolliert.
    Gleiche Grenze wie beim Retouren-Service, eine Outbox waere die Loesung.
    """
    try:
        broker.publish(event)
    except (AMQPError, OSError) as fehler:
        logger.warning(
            "Event {} fuer {} nicht gesendet, Broker nicht erreichbar: {}",
            event.event_type.value,
            event.retouren_id,
            fehler,
        )


def _pflichtfeld(context, wert: str, name: str) -> str:
    wert = wert.strip()
    if not wert:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"{name} fehlt")
    return wert


def _zeitpunkt(context, text: str) -> datetime:
    """Liest einen ISO-8601-Zeitstempel als UTC; ohne Angabe gilt die Jetztzeit."""
    text = text.strip()
    if not text:
        return datetime.now(UTC)
    try:
        zeit = datetime.fromisoformat(text)
    except ValueError:
        context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            f"scanned_at ist kein ISO-8601-Zeitstempel: {text}",
        )
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=UTC)
    return zeit.astimezone(UTC)


def _zustand(context, wert: int) -> Zustand:
    """Wandelt die Proto-Enum in den Zustand um; "nicht angegeben" ist ein Fehler."""
    try:
        name = warehouse_pb2.Condition.Name(wert)
    except ValueError:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"Unbekannter Zustand: {wert}")
    if wert == warehouse_pb2.CONDITION_UNSPECIFIED:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Zustand fehlt")
    return Zustand(name)


class WarehouseService(warehouse_pb2_grpc.WarehouseServiceServicer):
    def RegisterGoodsReceipt(self, request, context):
        """Wareneingang registrieren, Pruefrist setzen (Soll-BPMN).

        `already_cancelled` bildet das Gateway "Retoure bereits storniert?" ab.
        Eine stornierte Retoure behaelt ihren Status: ob sie wieder geoeffnet
        wird, entscheidet der Workflow (Sachbearbeitung), nicht das Lager.
        """
        retouren_id = _pflichtfeld(context, request.retouren_id, "retouren_id")
        scanner_id = _pflichtfeld(context, request.scanner_id, "scanner_id")
        eingang = _zeitpunkt(context, request.scanned_at)

        retoure = retourenakte.holen(retouren_id)
        if retoure is None:
            context.abort(
                grpc.StatusCode.NOT_FOUND, f"Retoure {retouren_id} nicht gefunden"
            )
        storniert = retoure.status == RetourenStatus.STORNIERT

        try:
            wareneingang = lager.wareneingang_erfassen(
                retouren_id, scanner_id, eingang, already_cancelled=storniert
            )
        except lager.WareneingangExistiert as fehler:
            # Doppelter Scan: der erste Eintrag bleibt, Status und Historie auch
            context.abort(grpc.StatusCode.ALREADY_EXISTS, str(fehler))
        if not storniert:
            retourenakte.status_setzen(
                retouren_id,
                RetourenStatus.WARE_EINGEGANGEN,
                quelle=QUELLE,
                bemerkung=f"Scanner {scanner_id}",
            )
        logger.info(
            "Wareneingang {} erfasst (Scanner {}, storniert: {})",
            retouren_id,
            scanner_id,
            storniert,
        )
        # Soll-BPMN: "Status: Ware eingegangen", auch bei einem Spaetzugang
        _melden(
            build_event(
                EventType.WARE_EINGEGANGEN,
                retouren_id,
                QUELLE,
                WareEingegangenPayload(
                    scanner_id=scanner_id,
                    pruef_frist=wareneingang.pruef_frist,
                    already_cancelled=wareneingang.already_cancelled,
                ),
            )
        )
        return warehouse_pb2.GoodsReceiptResponse(
            retouren_id=retouren_id,
            already_cancelled=wareneingang.already_cancelled,
            pruef_frist=wareneingang.pruef_frist,
        )

    def RecordInspection(self, request, context):
        """Zustand erfassen und im WMS speichern (Soll-BPMN).

        Voraussetzung ist ein registrierter Wareneingang. Eine stornierte Retoure
        wird erst geprueft, wenn der Workflow sie wieder geoeffnet hat.
        """
        retouren_id = _pflichtfeld(context, request.retouren_id, "retouren_id")
        zustand = _zustand(context, request.condition)
        pruefer = _pflichtfeld(context, request.inspector, "inspector")

        retoure = retourenakte.holen(retouren_id)
        if retoure is None:
            context.abort(
                grpc.StatusCode.NOT_FOUND, f"Retoure {retouren_id} nicht gefunden"
            )
        if lager.wareneingang_holen(retouren_id) is None:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"Zu {retouren_id} wurde noch kein Wareneingang registriert",
            )
        if retoure.status == RetourenStatus.STORNIERT:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"{retouren_id} ist storniert, erst die Wiedereroeffnung klaeren",
            )

        try:
            pruefung = lager.pruefung_erfassen(
                retouren_id,
                zustand,
                pruefer,
                request.note,
                list(request.photo_refs),
                erfasst=datetime.now(UTC),
            )
        except lager.PruefungExistiert as fehler:
            context.abort(grpc.StatusCode.ALREADY_EXISTS, str(fehler))
        retourenakte.status_setzen(
            retouren_id,
            RetourenStatus.PRUEFUNG_ABGESCHLOSSEN,
            quelle=QUELLE,
            bemerkung=f"{zustand.value} durch {pruefer}",
        )
        logger.info("Pruefung {} erfasst: {}", retouren_id, zustand.value)
        _melden(
            build_event(
                EventType.PRUEFUNG_ABGESCHLOSSEN,
                retouren_id,
                QUELLE,
                PruefungAbgeschlossenPayload(
                    condition=pruefung.zustand,
                    inspector=pruefung.pruefer,
                    note=pruefung.notiz,
                    photo_refs=list(pruefung.foto_refs),
                ),
            )
        )
        return warehouse_pb2.InspectionResponse(
            retouren_id=retouren_id,
            condition=warehouse_pb2.Condition.Value(pruefung.zustand.value),
            recorded_at=pruefung.erfasst_am,
        )

    def GetInspection(self, request, context):
        """Pruefergebnis zu einer Retoure abfragen.

        NOT_FOUND gilt sowohl fuer eine unbekannte Retouren-ID als auch fuer eine
        Retoure, die noch nicht geprueft wurde; die Meldung sagt, welcher Fall es ist.
        """
        retouren_id = _pflichtfeld(context, request.retouren_id, "retouren_id")
        if retourenakte.holen(retouren_id) is None:
            context.abort(
                grpc.StatusCode.NOT_FOUND, f"Retoure {retouren_id} nicht gefunden"
            )
        pruefung = lager.pruefung_holen(retouren_id)
        if pruefung is None:
            context.abort(
                grpc.StatusCode.NOT_FOUND,
                f"Zu {retouren_id} liegt noch kein Pruefergebnis vor",
            )
        return warehouse_pb2.InspectionResponse(
            retouren_id=retouren_id,
            condition=warehouse_pb2.Condition.Value(pruefung.zustand.value),
            recorded_at=pruefung.erfasst_am,
        )


def serve(address: str = "[::]:50051") -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    warehouse_pb2_grpc.add_WarehouseServiceServicer_to_server(
        WarehouseService(), server
    )
    server.add_insecure_port(address)
    server.start()
    logger.info("gRPC-Wareneingangs-Service laeuft auf {}", address)
    server.wait_for_termination()
