"""gRPC-Server in der Rolle des WMS. Zustaendig: Benjamin.

Wareneingang und Zustandserfassung (siehe docs/sprint2-plan.md, Abschnitt 4).
Die Retourenakte (`shopeasy.shared.retourenakte`) bleibt die Datenbasis, die
Lagerdaten liegen in `lager.py`.

TODO:
- Zustand erfassen und speichern, Fehlercodes: NOT_FOUND (unbekannte Retouren-ID),
  FAILED_PRECONDITION (Pruefung vor Wareneingang), INVALID_ARGUMENT (Zustand fehlt)
- nach Erfolg Events publizieren: ware.eingegangen, pruefung.abgeschlossen
"""

from concurrent import futures
from datetime import UTC, datetime

import grpc
from loguru import logger

from shopeasy.shared import retourenakte
from shopeasy.shared.models import RetourenStatus
from shopeasy.warehouse.v1 import warehouse_pb2, warehouse_pb2_grpc
from shopeasy.warehouse_grpc import lager

QUELLE = "warehouse-grpc"


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
        return warehouse_pb2.GoodsReceiptResponse(
            retouren_id=retouren_id,
            already_cancelled=wareneingang.already_cancelled,
            pruef_frist=wareneingang.pruef_frist,
        )

    def RecordInspection(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "noch nicht implementiert")

    def GetInspection(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "noch nicht implementiert")


def serve(address: str = "[::]:50051") -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    warehouse_pb2_grpc.add_WarehouseServiceServicer_to_server(
        WarehouseService(), server
    )
    server.add_insecure_port(address)
    server.start()
    logger.info("gRPC-Wareneingangs-Service laeuft auf {}", address)
    server.wait_for_termination()
