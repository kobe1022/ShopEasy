"""gRPC-Server in der Rolle des WMS. Zustaendig: Benjamin.

TODO (siehe docs/sprint2-plan.md, Abschnitt 4):
- Wareneingang registrieren: pruef_frist = 24 h nach Wareneingang,
  already_cancelled aus der Retourenakte lesen
- Zustand erfassen und speichern, Fehlercodes: NOT_FOUND (unbekannte Retouren-ID),
  FAILED_PRECONDITION (Pruefung vor Wareneingang), ALREADY_EXISTS (doppelter Scan),
  INVALID_ARGUMENT (Zustand fehlt)
- nach Erfolg Events publizieren: ware.eingegangen, pruefung.abgeschlossen
"""

from concurrent import futures

import grpc
from loguru import logger

from shopeasy.warehouse.v1 import warehouse_pb2_grpc


class WarehouseService(warehouse_pb2_grpc.WarehouseServiceServicer):
    def RegisterGoodsReceipt(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "noch nicht implementiert")

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
