"""Simulierte Scanner-App im Lager (gRPC-Client). Zustaendig: Benjamin.

Aufruf:
    uv run python -m shopeasy.clients.scanner_cli receive RET-2026-000123
    uv run python -m shopeasy.clients.scanner_cli inspect RET-2026-000123 NEUWERTIG
    uv run python -m shopeasy.clients.scanner_cli get RET-2026-000123
"""

import argparse
from datetime import UTC, datetime

import grpc

from shopeasy.shared.config import WAREHOUSE_GRPC_ADDRESS
from shopeasy.warehouse.v1 import warehouse_pb2, warehouse_pb2_grpc


def main() -> None:
    parser = argparse.ArgumentParser(prog="scanner_cli")
    sub = parser.add_subparsers(dest="command", required=True)

    receive = sub.add_parser("receive", help="Wareneingang melden")
    receive.add_argument("retouren_id")
    receive.add_argument("--scanner-id", default="LAGER-03")

    inspect = sub.add_parser("inspect", help="Zustand erfassen")
    inspect.add_argument("retouren_id")
    inspect.add_argument("condition", choices=warehouse_pb2.Condition.keys()[1:])
    inspect.add_argument("--inspector", default="lager")
    inspect.add_argument("--note", default="")
    inspect.add_argument("--photo", action="append", default=[])

    get = sub.add_parser("get", help="Pruefergebnis abfragen")
    get.add_argument("retouren_id")

    args = parser.parse_args()
    with grpc.insecure_channel(WAREHOUSE_GRPC_ADDRESS) as channel:
        stub = warehouse_pb2_grpc.WarehouseServiceStub(channel)
        try:
            if args.command == "receive":
                response = stub.RegisterGoodsReceipt(
                    warehouse_pb2.GoodsReceiptRequest(
                        retouren_id=args.retouren_id,
                        scanner_id=args.scanner_id,
                        scanned_at=datetime.now(UTC).isoformat(),
                    )
                )
            elif args.command == "inspect":
                response = stub.RecordInspection(
                    warehouse_pb2.InspectionRequest(
                        retouren_id=args.retouren_id,
                        condition=warehouse_pb2.Condition.Value(args.condition),
                        inspector=args.inspector,
                        note=args.note,
                        photo_refs=args.photo,
                    )
                )
            else:
                response = stub.GetInspection(
                    warehouse_pb2.RetourenIdRequest(retouren_id=args.retouren_id)
                )
        except grpc.RpcError as error:
            print(f"Fehler: {error.code().name}: {error.details()}")
            raise SystemExit(1) from error
    print(response)


if __name__ == "__main__":
    main()
