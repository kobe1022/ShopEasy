"""Simulierte Scanner-App im Lager (gRPC-Client). Zustaendig: Benjamin.

Aufruf (der Server muss laufen: uv run python -m shopeasy.warehouse_grpc):
    uv run python -m shopeasy.clients.scanner_cli receive RET-2026-000123
    uv run python -m shopeasy.clients.scanner_cli inspect RET-2026-000123 BESCHAEDIGT \\
        --note "Reissverschluss defekt" --photo foto-001.jpg
    uv run python -m shopeasy.clients.scanner_cli get RET-2026-000123

Beendigungscode: 0 = erledigt, 1 = der Server hat die Anfrage abgelehnt,
2 = der Server ist nicht erreichbar.
"""

import argparse
import sys
from datetime import UTC, datetime

import grpc

from shopeasy.shared import config
from shopeasy.warehouse.v1 import warehouse_pb2, warehouse_pb2_grpc

EXIT_OK = 0
EXIT_ABGELEHNT = 1
EXIT_NICHT_ERREICHBAR = 2

# Soll-BPMN: Bei Schaeden oder unklaren Faellen werden Fotos gemacht.
ZUSTAENDE_MIT_FOTO = ("BESCHAEDIGT", "UNVOLLSTAENDIG", "FALSCHER_ARTIKEL")

# Was ein Statuscode fuer die Person am Scanner bedeutet
FEHLERTITEL: dict[grpc.StatusCode, str] = {
    grpc.StatusCode.NOT_FOUND: "Nicht gefunden",
    grpc.StatusCode.ALREADY_EXISTS: "Bereits erfasst",
    grpc.StatusCode.FAILED_PRECONDITION: "Noch nicht moeglich",
    grpc.StatusCode.INVALID_ARGUMENT: "Ungueltige Eingabe",
}


def formatiere_eingang(antwort: warehouse_pb2.GoodsReceiptResponse) -> str:
    zeilen = [
        f"Wareneingang erfasst: {antwort.retouren_id}",
        f"  Pruefung faellig bis: {antwort.pruef_frist}",
    ]
    if antwort.already_cancelled:
        zeilen.append(
            "  ACHTUNG: Die Retoure ist bereits storniert. Ware beiseite legen,"
            " die Sachbearbeitung entscheidet ueber die Wiedereroeffnung."
        )
    return "\n".join(zeilen)


def formatiere_pruefung(antwort: warehouse_pb2.InspectionResponse) -> str:
    zustand = warehouse_pb2.Condition.Name(antwort.condition)
    return (
        f"Zustand {zustand} fuer {antwort.retouren_id}"
        f" (erfasst am {antwort.recorded_at})"
    )


def formatiere_fehler(fehler: grpc.RpcError, adresse: str) -> str:
    code = fehler.code()
    if code == grpc.StatusCode.UNAVAILABLE:
        return (
            f"Der Wareneingangs-Service unter {adresse} ist nicht erreichbar."
            " Laeuft er? (uv run python -m shopeasy.warehouse_grpc)"
        )
    if code == grpc.StatusCode.DEADLINE_EXCEEDED:
        return (
            f"Der Wareneingangs-Service unter {adresse} antwortet nicht rechtzeitig"
            " oder ist nicht erreichbar."
        )
    titel = FEHLERTITEL.get(code, code.name)
    return f"{titel}: {fehler.details()}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scanner_cli", description="Scanner-App im Lager (simuliert)"
    )
    parser.add_argument(
        "--server",
        default=config.WAREHOUSE_GRPC_ADDRESS,
        help="Adresse des Wareneingangs-Service (Standard: %(default)s)",
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Wartezeit in Sekunden"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    receive = sub.add_parser("receive", help="Wareneingang melden")
    receive.add_argument("retouren_id")
    receive.add_argument("--scanner-id", default="LAGER-03")

    inspect = sub.add_parser("inspect", help="Zustand erfassen")
    inspect.add_argument("retouren_id")
    inspect.add_argument(
        "condition",
        type=str.upper,
        choices=warehouse_pb2.Condition.keys()[1:],
        help="Zustand der Ware",
    )
    inspect.add_argument("--inspector", default="lager", help="Wer hat geprueft?")
    inspect.add_argument("--note", default="", help="Bemerkung zur Pruefung")
    inspect.add_argument(
        "--photo",
        action="append",
        default=[],
        help="Verweis auf ein Foto (mehrfach angebbar)",
    )

    get = sub.add_parser("get", help="Pruefergebnis abfragen")
    get.add_argument("retouren_id")
    return parser


def _aufrufen(args: argparse.Namespace, stub) -> str:
    """Fuehrt den gewaehlten Befehl aus und gibt die Ausgabe zurueck."""
    if args.command == "receive":
        antwort = stub.RegisterGoodsReceipt(
            warehouse_pb2.GoodsReceiptRequest(
                retouren_id=args.retouren_id,
                scanner_id=args.scanner_id,
                scanned_at=datetime.now(UTC).isoformat(),
            ),
            timeout=args.timeout,
        )
        return formatiere_eingang(antwort)
    if args.command == "inspect":
        if args.condition in ZUSTAENDE_MIT_FOTO and not args.photo:
            print(
                f"Hinweis: Bei {args.condition} sollen Fotos beigefuegt werden"
                " (--photo).",
                file=sys.stderr,
            )
        antwort = stub.RecordInspection(
            warehouse_pb2.InspectionRequest(
                retouren_id=args.retouren_id,
                condition=warehouse_pb2.Condition.Value(args.condition),
                inspector=args.inspector,
                note=args.note,
                photo_refs=args.photo,
            ),
            timeout=args.timeout,
        )
        return formatiere_pruefung(antwort)
    antwort = stub.GetInspection(
        warehouse_pb2.RetourenIdRequest(retouren_id=args.retouren_id),
        timeout=args.timeout,
    )
    return formatiere_pruefung(antwort)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with grpc.insecure_channel(args.server) as channel:
        stub = warehouse_pb2_grpc.WarehouseServiceStub(channel)
        try:
            ausgabe = _aufrufen(args, stub)
        except grpc.RpcError as fehler:
            print(f"Fehler: {formatiere_fehler(fehler, args.server)}", file=sys.stderr)
            if fehler.code() in (
                grpc.StatusCode.UNAVAILABLE,
                grpc.StatusCode.DEADLINE_EXCEEDED,
            ):
                return EXIT_NICHT_ERREICHBAR
            return EXIT_ABGELEHNT
    print(ausgabe)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
