"""Demo fuers Review: ein Retourenfall von der Marktplatz-Meldung bis zur
Zustandserfassung, dazu die wichtigsten Fehlerfaelle (Issue #27).

Voraussetzung: alle Dienste laufen.
    docker compose up -d --build

Aufruf (im Projektordner):
    uv run python scripts/demo.py             # laeuft durch
    uv run python scripts/demo.py --schritt   # wartet vor jedem Abschnitt auf Enter

Das Skript benutzt die Dienste ueber ihre echten Schnittstellen (REST, gRPC,
RabbitMQ), so wie es spaeter der Workflow tut. Es ist wiederholbar: jeder Lauf legt
eine neue Meldung mit eigener ID an.

Beendigungscode: 0 = alles wie erwartet, 1 = mindestens eine Pruefung ist
fehlgeschlagen, 2 = ein Dienst ist nicht erreichbar.
"""

import argparse
import csv
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import grpc
import httpx
import pika

from shopeasy.marketplace_mock.formate import ZalandoReturn
from shopeasy.shared import broker, config
from shopeasy.warehouse.v1 import warehouse_pb2, warehouse_pb2_grpc

PROJEKT = Path(__file__).resolve().parents[1]
MARKTPLATZ = config.MARKETPLACE_MOCK_URL
RETOUREN_SERVICE = f"http://127.0.0.1:{config.RETURN_SERVICE_PORT}"
GRPC_ADRESSE = config.WAREHOUSE_GRPC_ADDRESS
RABBIT_UI = "http://127.0.0.1:15672"
RABBIT_LOGIN = ("guest", "guest")

# Absichtlich kaputt: der Event-Typ stimmt, aber im Inhalt fehlt "condition".
KAPUTTE_NACHRICHT = (
    b'{"event_type": "pruefung.abgeschlossen", "retouren_id": "RET-2026-999999",'
    b' "source": "demo-skript", "payload": {"inspector": "demo"}}'
)


class Bericht:
    """Gibt die Schritte aus und merkt sich, was wie erwartet war."""

    def __init__(self, schrittweise: bool = False) -> None:
        self.schrittweise = schrittweise
        self.ergebnisse: list[tuple[str, bool]] = []

    def abschnitt(self, titel: str) -> None:
        print()
        print("=" * 72)
        print(titel)
        print("=" * 72)
        if self.schrittweise:
            input("  Weiter mit Enter ...")

    def zeige(self, text: str = "") -> None:
        print(f"  {text}" if text else "")

    def pruefe(self, beschreibung: str, bedingung: object, detail: object = "") -> bool:
        ok = bool(bedingung)
        self.ergebnisse.append((beschreibung, ok))
        zusatz = f"   ({detail})" if detail != "" and not ok else ""
        print(f"  [{'OK' if ok else 'FEHLER'}] {beschreibung}{zusatz}")
        return ok

    def zusammenfassung(self) -> int:
        """Gibt das Gesamtergebnis aus und liefert den Beendigungscode."""
        fehler = [text for text, ok in self.ergebnisse if not ok]
        print()
        print("=" * 72)
        print(
            f"Ergebnis: {len(self.ergebnisse) - len(fehler)} von {len(self.ergebnisse)} Pruefungen bestanden"
        )
        for text in fehler:
            print(f"  FEHLGESCHLAGEN: {text}")
        print("=" * 72)
        return 1 if fehler else 0


def neue_zalando_meldung(kennung: str | None = None) -> ZalandoReturn:
    """Eine frische Zalando-Retourenmeldung mit eigener ID (Format wie beim Mock)."""
    kennung = kennung or time.strftime("%H%M%S")
    heute = date.today()
    geliefert = heute - timedelta(days=6)
    return ZalandoReturn(
        id=f"ZRET-DEMO-{kennung}",
        order={
            "number": f"ORD-DEMO-{kennung}",
            "delivered_on": geliefert.strftime("%d.%m.%Y"),
        },
        customer={"email": "demo.kundin@example.org"},
        reason={"code": 30, "text": "Farbe anders als auf dem Foto"},
        announced_on=heute.strftime("%d.%m.%Y"),
        articles=[{"ean": "4012345000017", "qty": 1}],
    )


def warte(bedingung: Callable[[], object], sekunden: float = 12.0) -> bool:
    ende = time.time() + sekunden
    while time.time() < ende:
        if bedingung():
            return True
        time.sleep(0.5)
    return bool(bedingung())


def dienste_pruefen() -> list[str]:
    """Nennt die Dienste, die nicht antworten (leere Liste = alles da)."""
    fehlen = []
    for name, adresse in (
        ("Mock-Marktplatz", f"{MARKTPLATZ}/health"),
        ("Retouren-Service", f"{RETOUREN_SERVICE}/health"),
    ):
        try:
            httpx.get(adresse, timeout=3).raise_for_status()
        except httpx.HTTPError:
            fehlen.append(name)
    try:
        with grpc.insecure_channel(GRPC_ADRESSE) as kanal:
            grpc.channel_ready_future(kanal).result(timeout=3)
    except grpc.FutureTimeoutError:
        fehlen.append("gRPC-Wareneingang")
    try:
        broker.connect().close()
    except pika.exceptions.AMQPError, OSError:
        fehlen.append("RabbitMQ")
    return fehlen


def fehlercode(aufruf: Callable[[], object]) -> grpc.StatusCode | None:
    """Fuehrt einen gRPC-Aufruf aus und liefert den Fehlercode (None = kein Fehler)."""
    try:
        aufruf()
    except grpc.RpcError as fehler:
        return fehler.code()
    return None


def eventlog_zeilen(retouren_id: str) -> list[dict[str, str]]:
    pfad = PROJEKT / config.EVENTLOG_PATH
    if not pfad.exists():
        return []
    with pfad.open(newline="", encoding="utf-8") as datei:
        zeilen = csv.DictReader(datei, delimiter=";")
        return [z for z in zeilen if z["case_id"] == retouren_id]


def docker(*argumente: str) -> subprocess.CompletedProcess | None:
    """Fuehrt `docker compose ...` im Projektordner aus (None = Docker nicht verfuegbar)."""
    try:
        return subprocess.run(
            ["docker", "compose", *argumente],
            cwd=PROJEKT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,  # Rueckgabewert pruefen wir selbst
        )
    except OSError, subprocess.TimeoutExpired:
        return None


def status_mails(retouren_id: str) -> list[str] | None:
    """Liest die simulierten Status-Mails aus dem Log des Kundeninfo-Dienstes.

    None, wenn sich die Mails so nicht lesen lassen: Docker fehlt oder der Dienst
    laeuft nicht als Container (dann stehen die Mails im Terminal des Dienstes).
    """
    laeuft = docker("ps", "-q", "kundeninfo")
    if laeuft is None or laeuft.returncode != 0 or not laeuft.stdout.strip():
        return None
    ergebnis = docker("logs", "--no-color", "kundeninfo")
    if ergebnis is None or ergebnis.returncode != 0:
        return None
    return [
        zeile.split("Status-Mail an", 1)[1].strip()
        for zeile in ergebnis.stdout.splitlines()
        if "Status-Mail an" in zeile and retouren_id in zeile
    ]


def kaputte_nachricht_senden() -> None:
    with broker.connect() as verbindung:
        kanal = verbindung.channel()
        broker.declare_topology(kanal)
        kanal.basic_publish(
            exchange=broker.EXCHANGE,
            routing_key="pruefung.abgeschlossen",
            body=KAPUTTE_NACHRICHT,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
        )


def kaputte_nachricht_in_dlq() -> dict | None:
    """Sucht unsere kaputte Nachricht in der Fehler-Warteschlange (None = nicht da).

    Die Nachrichten bleiben dabei in der Warteschlange liegen (requeue).
    """
    try:
        antwort = httpx.post(
            f"{RABBIT_UI}/api/queues/%2F/retouren.dlq/get",
            auth=RABBIT_LOGIN,
            json={"count": 200, "ackmode": "ack_requeue_true", "encoding": "auto"},
            timeout=5,
        )
        antwort.raise_for_status()
    except httpx.HTTPError:
        return None
    for nachricht in antwort.json():
        if "demo-skript" in nachricht.get("payload", ""):
            return nachricht
    return None


# --- Hauptfall ---------------------------------------------------------------


def hauptfall(b: Bericht, http: httpx.Client, stub) -> tuple[str | None, ZalandoReturn]:
    meldung = neue_zalando_meldung()

    b.abschnitt("1. Der Marktplatz meldet eine Retoure (Mock-REST-API)")
    b.zeige(
        f"Zalando meldet {meldung.id}: Grund-Code {meldung.reason.code}, "
        f"EAN {meldung.articles[0].ean}, angemeldet am {meldung.announced_on}"
    )
    antwort = http.post(
        f"{MARKTPLATZ}/zalando/returns", json=meldung.model_dump(mode="json")
    )
    b.pruefe(
        "Mock-Marktplatz nimmt die Meldung an (201)",
        antwort.status_code == 201,
        antwort.status_code,
    )
    neu = http.get(f"{MARKTPLATZ}/zalando/returns", params={"status": "new"}).json()
    b.pruefe(
        "Die Meldung steht beim Marktplatz als 'neu' bereit",
        any(m["id"] == meldung.id for m in neu),
    )

    b.abschnitt(
        "2. ShopEasy holt die Meldung ab und legt die Retoure an (Retouren-Service)"
    )
    poll = http.post(f"{RETOUREN_SERVICE}/returns/poll", timeout=60).json()
    unsere = [e for e in poll["angelegt"] if e["externe_id"] == meldung.id]
    b.pruefe(
        "Der Retouren-Service hat die Meldung abgeholt und angelegt",
        len(unsere) == 1,
        poll,
    )
    if not unsere:
        return None, meldung
    retouren_id = unsere[0]["retouren_id"]
    anderes = len(poll["angelegt"]) - 1
    if anderes:
        b.zeige(
            f"(zusaetzlich {anderes} weitere neue Testmeldung(en) des Marktplatzes abgeholt)"
        )
    retoure = http.get(f"{RETOUREN_SERVICE}/returns/{retouren_id}").json()
    b.zeige(f"Retouren-Nummer:  {retouren_id}")
    b.zeige(
        f"Kanal:            {retoure['kanal']}  (Marktplatz-ID {retoure['externe_id']})"
    )
    b.zeige(f"Grund:            {retoure['grund_text']}")
    b.zeige(
        f"Artikel:          {', '.join(a['sku'] for a in retoure['artikel'])}  (aus der EAN umgewandelt)"
    )
    b.zeige(f"Status:           {retoure['status']}")
    b.pruefe(
        "Die Marktplatz-Meldung wurde quittiert (nicht mehr 'neu')",
        not any(
            m["id"] == meldung.id
            for m in http.get(
                f"{MARKTPLATZ}/zalando/returns", params={"status": "new"}
            ).json()
        ),
    )

    b.abschnitt("3. Die Ware kommt im Lager an (gRPC, Scanner-App)")
    eingang = stub.RegisterGoodsReceipt(
        warehouse_pb2.GoodsReceiptRequest(
            retouren_id=retouren_id,
            scanner_id="LAGER-DEMO",
            scanned_at=datetime.now(UTC).isoformat(),
        ),
        timeout=10,
    )
    b.zeige(f"Wareneingang gemeldet, Pruefung faellig bis {eingang.pruef_frist}")
    b.pruefe("Wareneingang erfasst, Frist gesetzt", eingang.pruef_frist.endswith("Z"))
    b.pruefe("Retoure war nicht storniert", eingang.already_cancelled is False)

    b.abschnitt("4. Das Lager erfasst den Zustand (gRPC)")
    pruefung = stub.RecordInspection(
        warehouse_pb2.InspectionRequest(
            retouren_id=retouren_id,
            condition=warehouse_pb2.BESCHAEDIGT,
            inspector="lager-demo",
            note="Naht an der Schulter offen",
            photo_refs=["demo-foto-001.jpg"],
        ),
        timeout=10,
    )
    b.zeige(f"Zustand BESCHAEDIGT erfasst am {pruefung.recorded_at}, mit Foto")
    abfrage = stub.GetInspection(
        warehouse_pb2.RetourenIdRequest(retouren_id=retouren_id), timeout=10
    )
    b.pruefe(
        "Das Pruefergebnis laesst sich wieder abfragen",
        abfrage.condition == warehouse_pb2.BESCHAEDIGT,
    )

    b.abschnitt("5. Verlauf der Retoure (eine gemeinsame Datenbasis)")
    retoure = http.get(f"{RETOUREN_SERVICE}/returns/{retouren_id}").json()
    for eintrag in retoure["historie"]:
        b.zeige(
            f"{eintrag['zeitpunkt']}  {eintrag['status']:<24} ({eintrag['quelle']})"
        )
    b.pruefe(
        "Verlauf zeigt: registriert, Ware eingegangen, Pruefung abgeschlossen",
        [e["status"] for e in retoure["historie"]]
        == ["REGISTRIERT", "WARE_EINGEGANGEN", "PRUEFUNG_ABGESCHLOSSEN"],
    )

    b.abschnitt("6. Statusmeldungen ueber RabbitMQ (Event-Log und Kunden-Mails)")
    b.pruefe(
        "Event-Log hat alle drei Meldungen",
        warte(lambda: len(eventlog_zeilen(retouren_id)) >= 3),
    )
    for zeile in eventlog_zeilen(retouren_id):
        b.zeige(f"{zeile['timestamp']}  {zeile['activity']:<24} von {zeile['source']}")
    mails = status_mails(retouren_id)
    if mails is None:
        b.zeige(
            "(Status-Mails: Der Kundeninfo-Dienst laeuft nicht in Docker. Die Mails stehen "
            "im Terminal des Dienstes, in Docker: 'docker compose logs kundeninfo')"
        )
    else:
        warte(lambda: len(status_mails(retouren_id) or []) >= 2)
        mails = status_mails(retouren_id) or []
        b.pruefe(
            "Kundeninfo hat Status-Mails geschrieben (Eingang, Wareneingang)",
            len(mails) >= 2,
            len(mails),
        )
        for mail in mails:
            b.zeige(mail[:150])
    return retouren_id, meldung


# --- Fehlerfaelle --------------------------------------------------------------


def fehlerfaelle(
    b: Bericht, http: httpx.Client, stub, retouren_id: str, meldung: ZalandoReturn
) -> None:
    b.abschnitt("7. Fehlerfall: dieselbe Meldung kommt noch einmal (REST)")
    erneut = http.post(
        f"{RETOUREN_SERVICE}/returns/marketplace/zalando",
        json=meldung.model_dump(mode="json"),
    )
    b.zeige(
        f"Antwort: {erneut.status_code} Conflict, bestehende Retoure {erneut.json()['detail'].get('retouren_id')}"
    )
    b.pruefe(
        "Doppelte Meldung wird mit 409 abgewiesen, keine zweite Retoure",
        erneut.status_code == 409,
    )
    b.pruefe(
        "... und nennt die bestehende Nummer",
        erneut.json()["detail"].get("retouren_id") == retouren_id,
    )
    http.post(
        f"{MARKTPLATZ}/zalando/returns", json=meldung.model_dump(mode="json")
    )  # Marktplatz sendet erneut
    poll = http.post(f"{RETOUREN_SERVICE}/returns/poll", timeout=60).json()
    b.pruefe(
        "Beim Abholen erkannt als Dublette, nur quittiert",
        [e["retouren_id"] for e in poll["dubletten"]] == [retouren_id],
        poll,
    )

    b.abschnitt("8. Fehlerfall: unbekannte Retouren-Nummer")
    code = fehlercode(
        lambda: stub.RegisterGoodsReceipt(
            warehouse_pb2.GoodsReceiptRequest(
                retouren_id="RET-2026-999999", scanner_id="LAGER-DEMO"
            ),
            timeout=10,
        )
    )
    b.zeige(
        f"gRPC-Wareneingang fuer RET-2026-999999: {code.name if code else 'kein Fehler'}"
    )
    b.pruefe("gRPC meldet NOT_FOUND", code == grpc.StatusCode.NOT_FOUND, code)
    rest = http.get(f"{RETOUREN_SERVICE}/returns/RET-2026-999999")
    b.pruefe("REST meldet 404", rest.status_code == 404, rest.status_code)

    b.abschnitt("9. Fehlerfall: derselbe Wareneingang wird zweimal gescannt")
    code = fehlercode(
        lambda: stub.RegisterGoodsReceipt(
            warehouse_pb2.GoodsReceiptRequest(
                retouren_id=retouren_id, scanner_id="LAGER-07"
            ),
            timeout=10,
        )
    )
    b.zeige(f"Zweiter Scan: {code.name if code else 'kein Fehler'}")
    b.pruefe(
        "Zweiter Scan wird mit ALREADY_EXISTS abgewiesen",
        code == grpc.StatusCode.ALREADY_EXISTS,
        code,
    )

    b.abschnitt("10. Fehlerfaelle im Lager: zu frueh geprueft, Schaden ohne Foto")
    webshop = http.post(
        f"{RETOUREN_SERVICE}/returns",
        json={
            "bestell_nr": "ORD-DEMO-WEB",
            "kunde_email": "demo.kundin@example.org",
            "grund_text": "Passt nicht",
            "artikel": [{"sku": "JEANS-SLIM-32", "menge": 1}],
        },
    ).json()["retouren_id"]
    b.zeige(f"Neue Webshop-Retoure {webshop} (noch kein Wareneingang)")
    code = fehlercode(
        lambda: stub.RecordInspection(
            warehouse_pb2.InspectionRequest(
                retouren_id=webshop,
                condition=warehouse_pb2.NEUWERTIG,
                inspector="lager-demo",
            ),
            timeout=10,
        )
    )
    b.zeige(f"Pruefung vor dem Wareneingang: {code.name if code else 'kein Fehler'}")
    b.pruefe(
        "Pruefung vor dem Wareneingang: FAILED_PRECONDITION",
        code == grpc.StatusCode.FAILED_PRECONDITION,
        code,
    )
    stub.RegisterGoodsReceipt(
        warehouse_pb2.GoodsReceiptRequest(retouren_id=webshop, scanner_id="LAGER-DEMO"),
        timeout=10,
    )
    code = fehlercode(
        lambda: stub.RecordInspection(
            warehouse_pb2.InspectionRequest(
                retouren_id=webshop,
                condition=warehouse_pb2.BESCHAEDIGT,
                inspector="lager-demo",
            ),
            timeout=10,
        )
    )
    b.zeige(f"Schaden ohne Foto: {code.name if code else 'kein Fehler'}")
    b.pruefe(
        "Schaden ohne Foto: INVALID_ARGUMENT (Fotopflicht)",
        code == grpc.StatusCode.INVALID_ARGUMENT,
        code,
    )

    b.abschnitt("11. Fehlerfall: kaputte Nachricht im Broker (Fehler-Warteschlange)")
    b.zeige("Gesendet wird ein Pruefergebnis ohne Zustand ('condition' fehlt).")
    kaputte_nachricht_senden()
    gefunden: dict | None = None

    def suche() -> bool:
        nonlocal gefunden
        gefunden = kaputte_nachricht_in_dlq()
        return gefunden is not None

    b.pruefe(
        "Die Nachricht landet in der Fehler-Warteschlange retouren.dlq",
        warte(suche, 15),
    )
    if gefunden:
        tod = (
            gefunden.get("properties", {}).get("headers", {}).get("x-death") or [{}]
        )[0]
        b.zeige(
            f"Abgelehnt von Warteschlange '{tod.get('queue')}', Grund: {tod.get('reason')}"
        )
        b.zeige(
            "Die Nachricht ist nicht verloren: sie liegt in retouren.dlq und kann geprueft werden."
        )
    else:
        b.zeige(
            f"(RabbitMQ-Oberflaeche: {RABBIT_UI}, Reiter 'Queues', Eintrag retouren.dlq)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo fuers Review")
    parser.add_argument(
        "--schritt", action="store_true", help="vor jedem Abschnitt auf Enter warten"
    )
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Umlaute auch in alten Konsolen

    fehlen = dienste_pruefen()
    if fehlen:
        print("Nicht erreichbar: " + ", ".join(fehlen))
        print("Bitte zuerst alles starten:  docker compose up -d --build")
        return 2

    b = Bericht(schrittweise=args.schritt)
    print("ShopEasy: Demo der Sprint-2-Bausteine (Mock-REST, gRPC, RabbitMQ)")
    with httpx.Client(timeout=15) as http, grpc.insecure_channel(GRPC_ADRESSE) as kanal:
        stub = warehouse_pb2_grpc.WarehouseServiceStub(kanal)
        retouren_id, meldung = hauptfall(b, http, stub)
        if retouren_id:
            fehlerfaelle(b, http, stub, retouren_id, meldung)
        else:
            b.zeige(
                "Die Fehlerfaelle werden uebersprungen, weil der Hauptfall nicht lief."
            )
    return b.zusammenfassung()


if __name__ == "__main__":
    raise SystemExit(main())
