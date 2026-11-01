"""Tests fuer den gRPC-Wareneingangs-Service (Issues #15-#19).

Der Server laeuft im Test echt (eigener Port, eigene Retourenakte je Test), die
Aufrufe gehen ueber einen gRPC-Kanal. So sind auch die Statuscodes getestet.
"""

from concurrent import futures
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from pika.exceptions import AMQPConnectionError

from shopeasy.shared import broker, retourenakte
from shopeasy.shared.events import (
    Event,
    EventType,
    PruefungAbgeschlossenPayload,
    WareEingegangenPayload,
    parse_payload,
)
from shopeasy.shared.models import (
    Artikel,
    Kanal,
    NeueRetoure,
    RetourenStatus,
    Zustand,
)
from shopeasy.warehouse.v1 import warehouse_pb2
from shopeasy.warehouse_grpc import lager as lager_modul


def neue_retoure() -> str:
    """Legt eine Retoure in der (Test-)Akte an und gibt die Retouren-ID zurueck."""
    return retourenakte.anlegen(
        NeueRetoure(
            kanal=Kanal.WEBSHOP,
            bestell_nr="ORD-100300",
            kunde_email="max@example.org",
            grund_text="Farbe gefaellt nicht",
            artikel=[Artikel(sku="SHIRT-WEISS-L")],
        ),
        quelle="test",
    ).retouren_id


def eingang(stub, retouren_id, scanned_at="2026-11-02T09:00:00Z", scanner="LAGER-03"):
    return stub.RegisterGoodsReceipt(
        warehouse_pb2.GoodsReceiptRequest(
            retouren_id=retouren_id, scanner_id=scanner, scanned_at=scanned_at
        )
    )


def fehlercode(aufruf) -> grpc.StatusCode:
    with pytest.raises(grpc.RpcError) as fehler:
        aufruf()
    return fehler.value.code()


# --- RegisterGoodsReceipt (#15) ---------------------------------------------


def test_wareneingang_setzt_pruefrist_24_stunden_spaeter(lager):
    stub, _ = lager
    retouren_id = neue_retoure()

    antwort = eingang(stub, retouren_id, "2026-11-02T09:00:00Z")

    assert antwort.retouren_id == retouren_id
    assert antwort.already_cancelled is False
    assert antwort.pruef_frist == "2026-11-03T09:00:00Z"


def test_wareneingang_setzt_status_und_historie(lager):
    stub, _ = lager
    retouren_id = neue_retoure()

    eingang(stub, retouren_id)

    assert retourenakte.holen(retouren_id).status == RetourenStatus.WARE_EINGEGANGEN
    letzter = retourenakte.historie(retouren_id)[-1]
    assert letzter.status == RetourenStatus.WARE_EINGEGANGEN
    assert letzter.quelle == "warehouse-grpc"


def test_zeitstempel_mit_zeitzone_wird_nach_utc_umgerechnet(lager):
    stub, _ = lager

    antwort = eingang(stub, neue_retoure(), "2026-11-02T10:00:00+01:00")

    assert antwort.pruef_frist == "2026-11-03T09:00:00Z"


def test_ohne_zeitstempel_gilt_die_jetztzeit(lager):
    stub, _ = lager

    antwort = eingang(stub, neue_retoure(), scanned_at="")

    frist = datetime.strptime(antwort.pruef_frist, "%Y-%m-%dT%H:%M:%SZ")
    erwartet = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24)
    assert abs(frist - erwartet) < timedelta(minutes=1)


def test_unbekannte_retoure_ist_not_found(lager):
    stub, _ = lager

    assert (
        fehlercode(lambda: eingang(stub, "RET-2026-999999"))
        == grpc.StatusCode.NOT_FOUND
    )


def test_stornierte_retoure_meldet_already_cancelled_und_behaelt_status(lager):
    stub, _ = lager
    retouren_id = neue_retoure()
    retourenakte.status_setzen(retouren_id, RetourenStatus.STORNIERT, quelle="test")

    antwort = eingang(stub, retouren_id)

    assert antwort.already_cancelled is True
    assert retourenakte.holen(retouren_id).status == RetourenStatus.STORNIERT


@pytest.mark.parametrize(
    ("retouren_id", "scanner_id", "scanned_at"),
    [
        ("", "LAGER-03", "2026-11-02T09:00:00Z"),
        ("RET-2026-000001", "", "2026-11-02T09:00:00Z"),
        ("RET-2026-000001", "LAGER-03", "gestern Nachmittag"),
    ],
)
def test_fehlende_oder_ungueltige_angaben_sind_invalid_argument(
    lager, retouren_id, scanner_id, scanned_at
):
    stub, _ = lager

    code = fehlercode(lambda: eingang(stub, retouren_id, scanned_at, scanner_id))

    assert code == grpc.StatusCode.INVALID_ARGUMENT


# --- Doppelter Scan (#16) ---------------------------------------------------


def test_doppelter_scan_ist_already_exists(lager):
    stub, _ = lager
    retouren_id = neue_retoure()
    eingang(stub, retouren_id)

    code = fehlercode(lambda: eingang(stub, retouren_id, scanner="LAGER-07"))

    assert code == grpc.StatusCode.ALREADY_EXISTS


def test_doppelter_scan_aendert_nichts(lager):
    stub, _ = lager
    retouren_id = neue_retoure()
    eingang(stub, retouren_id, "2026-11-02T09:00:00Z", scanner="LAGER-03")
    historie_vorher = retourenakte.historie(retouren_id)

    fehlercode(
        lambda: eingang(stub, retouren_id, "2026-11-02T15:00:00Z", scanner="LAGER-07")
    )

    ersterfasst = lager_modul.wareneingang_holen(retouren_id)
    assert ersterfasst.scanner_id == "LAGER-03"
    assert ersterfasst.pruef_frist == "2026-11-03T09:00:00Z"
    assert retourenakte.historie(retouren_id) == historie_vorher


def test_fehlermeldung_nennt_den_ersten_scan(lager):
    stub, _ = lager
    retouren_id = neue_retoure()
    eingang(stub, retouren_id, "2026-11-02T09:00:00Z", scanner="LAGER-03")

    with pytest.raises(grpc.RpcError) as fehler:
        eingang(stub, retouren_id)

    assert "LAGER-03" in fehler.value.details()
    assert "2026-11-02T09:00:00Z" in fehler.value.details()


def test_gleichzeitige_scans_ergeben_genau_einen_eingang(lager):
    stub, _ = lager
    retouren_id = neue_retoure()

    def scannen(nummer):
        try:
            eingang(stub, retouren_id, scanner=f"LAGER-{nummer:02d}")
        except grpc.RpcError as fehler:
            return fehler.code()
        return grpc.StatusCode.OK

    with futures.ThreadPoolExecutor(max_workers=4) as pool:
        ergebnisse = list(pool.map(scannen, range(8)))

    assert ergebnisse.count(grpc.StatusCode.OK) == 1
    assert ergebnisse.count(grpc.StatusCode.ALREADY_EXISTS) == 7
    eintraege = [
        e
        for e in retourenakte.historie(retouren_id)
        if e.status == RetourenStatus.WARE_EINGEGANGEN
    ]
    assert len(eintraege) == 1


# --- RecordInspection (#17) -------------------------------------------------


def pruefen(
    stub,
    retouren_id,
    zustand=warehouse_pb2.NEUWERTIG,
    pruefer="lager-01",
    notiz="",
    fotos=(),
):
    return stub.RecordInspection(
        warehouse_pb2.InspectionRequest(
            retouren_id=retouren_id,
            condition=zustand,
            inspector=pruefer,
            note=notiz,
            photo_refs=fotos,
        )
    )


def retoure_mit_eingang(stub) -> str:
    retouren_id = neue_retoure()
    eingang(stub, retouren_id)
    return retouren_id


def test_zustand_wird_gespeichert(lager):
    stub, _ = lager
    retouren_id = retoure_mit_eingang(stub)

    antwort = pruefen(
        stub,
        retouren_id,
        warehouse_pb2.BESCHAEDIGT,
        notiz="Reissverschluss defekt",
        fotos=["foto-001.jpg", "foto-002.jpg"],
    )

    assert antwort.retouren_id == retouren_id
    assert antwort.condition == warehouse_pb2.BESCHAEDIGT
    assert antwort.recorded_at.endswith("Z")
    gespeichert = lager_modul.pruefung_holen(retouren_id)
    assert gespeichert.zustand == Zustand.BESCHAEDIGT
    assert gespeichert.pruefer == "lager-01"
    assert gespeichert.notiz == "Reissverschluss defekt"
    assert gespeichert.foto_refs == ("foto-001.jpg", "foto-002.jpg")


def test_pruefung_setzt_status_und_historie(lager):
    stub, _ = lager
    retouren_id = retoure_mit_eingang(stub)

    pruefen(stub, retouren_id, warehouse_pb2.GETRAGEN)

    assert (
        retourenakte.holen(retouren_id).status == RetourenStatus.PRUEFUNG_ABGESCHLOSSEN
    )
    letzter = retourenakte.historie(retouren_id)[-1]
    assert letzter.quelle == "warehouse-grpc"
    assert "GETRAGEN" in letzter.bemerkung


@pytest.mark.parametrize("zustand", list(warehouse_pb2.Condition.values())[1:])
def test_alle_zustaende_werden_angenommen(lager, zustand):
    stub, _ = lager

    antwort = pruefen(stub, retoure_mit_eingang(stub), zustand)

    assert antwort.condition == zustand


@pytest.mark.parametrize(
    ("zustand", "pruefer"),
    [
        (warehouse_pb2.CONDITION_UNSPECIFIED, "lager-01"),  # Zustand fehlt
        (99, "lager-01"),  # unbekannter Wert
        (warehouse_pb2.NEUWERTIG, ""),  # Pruefer fehlt
    ],
)
def test_fehlender_zustand_oder_pruefer_ist_invalid_argument(lager, zustand, pruefer):
    stub, _ = lager
    retouren_id = retoure_mit_eingang(stub)

    code = fehlercode(lambda: pruefen(stub, retouren_id, zustand, pruefer))

    assert code == grpc.StatusCode.INVALID_ARGUMENT
    assert lager_modul.pruefung_holen(retouren_id) is None


def test_fehlende_retouren_id_ist_invalid_argument(lager):
    stub, _ = lager

    assert fehlercode(lambda: pruefen(stub, "")) == grpc.StatusCode.INVALID_ARGUMENT


def test_pruefung_unbekannter_retoure_ist_not_found(lager):
    stub, _ = lager

    code = fehlercode(lambda: pruefen(stub, "RET-2026-999999"))

    assert code == grpc.StatusCode.NOT_FOUND


def test_pruefung_vor_wareneingang_ist_failed_precondition(lager):
    stub, _ = lager
    retouren_id = neue_retoure()

    code = fehlercode(lambda: pruefen(stub, retouren_id))

    assert code == grpc.StatusCode.FAILED_PRECONDITION
    assert lager_modul.pruefung_holen(retouren_id) is None
    assert retourenakte.holen(retouren_id).status == RetourenStatus.REGISTRIERT


def test_pruefung_einer_stornierten_retoure_ist_failed_precondition(lager):
    stub, _ = lager
    retouren_id = neue_retoure()
    retourenakte.status_setzen(retouren_id, RetourenStatus.STORNIERT, quelle="test")
    eingang(stub, retouren_id)  # Spaetzugang, Retoure bleibt storniert

    code = fehlercode(lambda: pruefen(stub, retouren_id))

    assert code == grpc.StatusCode.FAILED_PRECONDITION
    assert retourenakte.holen(retouren_id).status == RetourenStatus.STORNIERT


def test_zweite_pruefung_ist_already_exists_und_aendert_nichts(lager):
    stub, _ = lager
    retouren_id = retoure_mit_eingang(stub)
    pruefen(stub, retouren_id, warehouse_pb2.NEUWERTIG, pruefer="lager-01")

    code = fehlercode(
        lambda: pruefen(stub, retouren_id, warehouse_pb2.BESCHAEDIGT, "lager-02")
    )

    assert code == grpc.StatusCode.ALREADY_EXISTS
    gespeichert = lager_modul.pruefung_holen(retouren_id)
    assert (gespeichert.zustand, gespeichert.pruefer) == (Zustand.NEUWERTIG, "lager-01")


# --- GetInspection (#18) ----------------------------------------------------


def abfragen(stub, retouren_id):
    return stub.GetInspection(warehouse_pb2.RetourenIdRequest(retouren_id=retouren_id))


def test_pruefergebnis_wird_geliefert(lager):
    stub, _ = lager
    retouren_id = retoure_mit_eingang(stub)
    gespeichert = pruefen(stub, retouren_id, warehouse_pb2.UNVOLLSTAENDIG)

    antwort = abfragen(stub, retouren_id)

    assert antwort.retouren_id == retouren_id
    assert antwort.condition == warehouse_pb2.UNVOLLSTAENDIG
    assert antwort.recorded_at == gespeichert.recorded_at


def test_abfrage_unbekannter_retoure_ist_not_found(lager):
    stub, _ = lager

    with pytest.raises(grpc.RpcError) as fehler:
        abfragen(stub, "RET-2026-999999")

    assert fehler.value.code() == grpc.StatusCode.NOT_FOUND
    assert "nicht gefunden" in fehler.value.details()


def test_abfrage_ohne_pruefergebnis_ist_not_found(lager):
    stub, _ = lager
    retouren_id = retoure_mit_eingang(stub)  # geliefert, aber noch nicht geprueft

    with pytest.raises(grpc.RpcError) as fehler:
        abfragen(stub, retouren_id)

    assert fehler.value.code() == grpc.StatusCode.NOT_FOUND
    assert "noch kein Pruefergebnis" in fehler.value.details()


def test_abfrage_ohne_retouren_id_ist_invalid_argument(lager):
    stub, _ = lager

    assert fehlercode(lambda: abfragen(stub, "")) == grpc.StatusCode.INVALID_ARGUMENT


def test_abfrage_veraendert_nichts(lager):
    stub, _ = lager
    retouren_id = retoure_mit_eingang(stub)
    pruefen(stub, retouren_id)
    historie_vorher = retourenakte.historie(retouren_id)

    abfragen(stub, retouren_id)
    abfragen(stub, retouren_id)

    assert retourenakte.historie(retouren_id) == historie_vorher


# --- Events (#19) -----------------------------------------------------------


def test_wareneingang_sendet_ware_eingegangen(lager):
    stub, gesendet = lager
    retouren_id = neue_retoure()

    eingang(stub, retouren_id, "2026-11-02T09:00:00Z", scanner="LAGER-03")

    assert len(gesendet) == 1
    event = gesendet[0]
    assert event.event_type == EventType.WARE_EINGEGANGEN
    assert event.retouren_id == retouren_id
    assert event.source == "warehouse-grpc"
    assert parse_payload(event) == WareEingegangenPayload(
        scanner_id="LAGER-03",
        pruef_frist="2026-11-03T09:00:00Z",
        already_cancelled=False,
    )


def test_spaetzugang_sendet_ware_eingegangen_mit_already_cancelled(lager):
    stub, gesendet = lager
    retouren_id = neue_retoure()
    retourenakte.status_setzen(retouren_id, RetourenStatus.STORNIERT, quelle="test")

    eingang(stub, retouren_id)

    assert [e.event_type for e in gesendet] == [EventType.WARE_EINGEGANGEN]
    assert parse_payload(gesendet[0]).already_cancelled is True


def test_pruefung_sendet_pruefung_abgeschlossen(lager):
    stub, gesendet = lager
    retouren_id = retoure_mit_eingang(stub)
    gesendet.clear()

    pruefen(
        stub,
        retouren_id,
        warehouse_pb2.BESCHAEDIGT,
        pruefer="lager-02",
        notiz="Naht offen",
        fotos=["foto-001.jpg"],
    )

    assert len(gesendet) == 1
    event = gesendet[0]
    assert event.event_type == EventType.PRUEFUNG_ABGESCHLOSSEN
    assert event.retouren_id == retouren_id
    assert event.source == "warehouse-grpc"
    assert parse_payload(event) == PruefungAbgeschlossenPayload(
        condition=Zustand.BESCHAEDIGT,
        inspector="lager-02",
        note="Naht offen",
        photo_refs=["foto-001.jpg"],
    )


def test_fehlerhafte_aufrufe_senden_kein_event(lager):
    stub, gesendet = lager
    retouren_id = retoure_mit_eingang(stub)
    pruefen(stub, retouren_id)
    gesendet.clear()

    fehlercode(lambda: eingang(stub, retouren_id))  # doppelter Scan
    fehlercode(lambda: pruefen(stub, retouren_id))  # zweite Pruefung
    fehlercode(lambda: eingang(stub, "RET-2026-999999"))  # unbekannt
    fehlercode(lambda: pruefen(stub, retouren_id, warehouse_pb2.CONDITION_UNSPECIFIED))

    assert gesendet == []


def test_events_passen_zum_event_log(lager):
    """Die Payloads muessen den Event-Log-Consumer passieren (parse_payload)."""
    stub, gesendet = lager

    pruefen(stub, retoure_mit_eingang(stub))

    assert len(gesendet) == 2
    for event in gesendet:
        parse_payload(Event.model_validate_json(event.model_dump_json()))


def test_ausfall_des_brokers_laesst_den_aufruf_gelingen(lager, monkeypatch):
    stub, _ = lager

    def broker_aus(event):
        raise AMQPConnectionError("Broker nicht erreichbar")

    monkeypatch.setattr(broker, "publish", broker_aus)
    retouren_id = neue_retoure()

    antwort = eingang(stub, retouren_id)
    pruefen(stub, retouren_id)

    assert antwort.pruef_frist
    assert lager_modul.wareneingang_holen(retouren_id) is not None
    assert lager_modul.pruefung_holen(retouren_id) is not None
