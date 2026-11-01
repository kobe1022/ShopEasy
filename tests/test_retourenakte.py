"""Tests fuer Issues #1-#3: Event-Payloads, Retourenmodell, Retourenakte."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from shopeasy.shared import retourenakte
from shopeasy.shared.events import (
    EVENT_ZU_STATUS,
    PAYLOAD_MODELS,
    Event,
    EventType,
    RetoureRegistriertPayload,
    WareEingegangenPayload,
    build_event,
    parse_payload,
)
from shopeasy.shared.models import (
    Artikel,
    Kanal,
    NeueRetoure,
    RetourenStatus,
    format_retouren_id,
    ist_retouren_id,
)
from shopeasy.shared.retourenakte import DubletteError, RetoureNichtGefunden


@pytest.fixture
def db(tmp_path):
    return tmp_path / "retourenakte.db"


def zalando_retoure(externe_id: str = "ZRET-2026-001002") -> NeueRetoure:
    return NeueRetoure(
        kanal=Kanal.ZALANDO,
        externe_id=externe_id,
        bestell_nr="ORD-100234",
        kunde_email="kundin@example.com",
        grund_text="Zu gross, passt nicht",
        artikel=[Artikel(sku="PULLI-BLAU-M", menge=1), Artikel(sku="SCHAL-ROT")],
        gemeldet_am=date(2026, 11, 2),
        geliefert_am=date(2026, 10, 28),
    )


def webshop_retoure() -> NeueRetoure:
    return NeueRetoure(
        kanal=Kanal.WEBSHOP,
        bestell_nr="ORD-100300",
        kunde_email="max@example.org",
        grund_text="Farbe gefaellt nicht",
        artikel=[Artikel(sku="SHIRT-WEISS-L")],
    )


# --- Issue #3: Modell und Retouren-ID ---------------------------------------


def test_format_retouren_id():
    assert format_retouren_id(2026, 1) == "RET-2026-000001"
    assert format_retouren_id(2026, 123) == "RET-2026-000123"
    assert ist_retouren_id("RET-2026-000123")
    assert not ist_retouren_id("R-0001")
    with pytest.raises(ValueError):
        format_retouren_id(2026, 0)


def test_marktplatz_braucht_externe_id():
    with pytest.raises(ValidationError):
        NeueRetoure(
            kanal=Kanal.AMAZON,
            bestell_nr="ORD-1",
            kunde_email="a@example.com",
            grund_text="defekt",
            artikel=[Artikel(sku="X")],
        )


@pytest.mark.parametrize(
    "feld, wert",
    [("kunde_email", "keine-mail"), ("artikel", []), ("grund_text", "")],
)
def test_validierung(feld, wert):
    daten = webshop_retoure().model_dump() | {feld: wert}
    with pytest.raises(ValidationError):
        NeueRetoure(**daten)


# --- Issue #2: Retourenakte -------------------------------------------------


def test_anlegen_und_holen(db):
    angelegt = retourenakte.anlegen(
        zalando_retoure(), quelle="retouren-service", db_path=db
    )

    assert angelegt.retouren_id == f"RET-{datetime.now(UTC).year}-000001"
    assert angelegt.status == RetourenStatus.REGISTRIERT
    assert [a.sku for a in angelegt.artikel] == ["PULLI-BLAU-M", "SCHAL-ROT"]
    assert angelegt.gemeldet_am == date(2026, 11, 2)
    assert angelegt.geliefert_am == date(2026, 10, 28)
    assert retourenakte.holen(angelegt.retouren_id, db_path=db) == angelegt


def test_ids_fortlaufend_und_pro_jahr(db):
    jan = datetime(2026, 1, 5, tzinfo=UTC)
    ids = [
        retourenakte.anlegen(
            webshop_retoure(), "test", db_path=db, jetzt=jan
        ).retouren_id
        for _ in range(3)
    ]
    assert ids == ["RET-2026-000001", "RET-2026-000002", "RET-2026-000003"]

    neujahr = datetime(2027, 1, 1, tzinfo=UTC)
    naechste = retourenakte.anlegen(
        webshop_retoure(), "test", db_path=db, jetzt=neujahr
    )
    assert naechste.retouren_id == "RET-2027-000001"


def test_ids_bleiben_nach_neustart_eindeutig(db):
    erste = retourenakte.anlegen(webshop_retoure(), "test", db_path=db)
    # jede Funktion oeffnet eine neue Verbindung, wie nach einem Neustart
    zweite = retourenakte.anlegen(webshop_retoure(), "test", db_path=db)
    assert erste.retouren_id != zweite.retouren_id


def test_dublette(db):
    erste = retourenakte.anlegen(zalando_retoure(), "test", db_path=db)
    with pytest.raises(DubletteError) as fehler:
        retourenakte.anlegen(zalando_retoure(), "test", db_path=db)
    assert fehler.value.bestehende_id == erste.retouren_id

    # gleiche externe ID bei anderem Marktplatz ist keine Dublette
    amazon = zalando_retoure().model_copy(update={"kanal": Kanal.AMAZON})
    retourenakte.anlegen(amazon, "test", db_path=db)
    # Webshop-Retouren ohne externe ID sind nie Dubletten
    retourenakte.anlegen(webshop_retoure(), "test", db_path=db)
    retourenakte.anlegen(webshop_retoure(), "test", db_path=db)


def test_dublette_vergibt_keine_id(db):
    retourenakte.anlegen(zalando_retoure(), "test", db_path=db)
    with pytest.raises(DubletteError):
        retourenakte.anlegen(zalando_retoure(), "test", db_path=db)
    naechste = retourenakte.anlegen(webshop_retoure(), "test", db_path=db)
    assert naechste.retouren_id.endswith("-000002")


def test_finde_per_externer_id(db):
    angelegt = retourenakte.anlegen(zalando_retoure(), "test", db_path=db)
    gefunden = retourenakte.finde_per_externer_id(
        Kanal.ZALANDO, "ZRET-2026-001002", db_path=db
    )
    assert gefunden == angelegt
    assert (
        retourenakte.finde_per_externer_id(Kanal.ZALANDO, "gibt-es-nicht", db_path=db)
        is None
    )


def test_holen_unbekannt(db):
    assert retourenakte.holen("RET-2026-999999", db_path=db) is None


def test_status_und_historie(db):
    r = retourenakte.anlegen(zalando_retoure(), "retouren-service", db_path=db)
    geaendert = retourenakte.status_setzen(
        r.retouren_id,
        RetourenStatus.WARE_EINGEGANGEN,
        quelle="warehouse-grpc",
        bemerkung="Scanner LAGER-03",
        db_path=db,
    )
    assert geaendert.status == RetourenStatus.WARE_EINGEGANGEN

    verlauf = retourenakte.historie(r.retouren_id, db_path=db)
    assert [e.status for e in verlauf] == [
        RetourenStatus.REGISTRIERT,
        RetourenStatus.WARE_EINGEGANGEN,
    ]
    assert verlauf[0].bemerkung == "Eingang ueber ZALANDO"
    assert verlauf[1].quelle == "warehouse-grpc"


def test_status_unbekannte_retoure(db):
    with pytest.raises(RetoureNichtGefunden):
        retourenakte.status_setzen(
            "RET-2026-999999", RetourenStatus.STORNIERT, "test", db_path=db
        )
    with pytest.raises(RetoureNichtGefunden):
        retourenakte.historie("RET-2026-999999", db_path=db)


# --- Issue #1: Event-Payloads -----------------------------------------------


def test_jeder_event_typ_hat_payload_und_status():
    assert set(PAYLOAD_MODELS) == set(EventType)
    assert set(EVENT_ZU_STATUS) == set(EventType)


def test_build_und_parse_event():
    payload = WareEingegangenPayload(
        scanner_id="LAGER-03", pruef_frist="2026-11-03T09:41:12Z"
    )
    event = build_event(
        EventType.WARE_EINGEGANGEN, "RET-2026-000123", "warehouse-grpc", payload
    )

    # ueber den Broker geht das Event als JSON
    empfangen = Event.model_validate_json(event.model_dump_json())
    assert parse_payload(empfangen) == payload
    assert empfangen.payload["already_cancelled"] is False


def test_build_event_falscher_payload():
    with pytest.raises(TypeError):
        build_event(
            EventType.RETOURE_REGISTRIERT,
            "RET-2026-000123",
            "test",
            WareEingegangenPayload(scanner_id="X", pruef_frist="2026-11-03T00:00:00Z"),
        )


def test_registriert_payload_aus_retoure(db):
    r = retourenakte.anlegen(zalando_retoure(), "retouren-service", db_path=db)
    payload = RetoureRegistriertPayload(
        **r.model_dump(include=set(RetoureRegistriertPayload.model_fields))
    )
    event = build_event(
        EventType.RETOURE_REGISTRIERT, r.retouren_id, "retouren-service", payload
    )
    assert event.payload["kanal"] == "ZALANDO"
    assert event.payload["artikel"][0] == {"sku": "PULLI-BLAU-M", "menge": 1}


def test_alte_datenbank_wird_nachgeruestet(db):
    """Eine Akte aus der ersten Version (ohne geliefert_am) bleibt nutzbar."""
    import sqlite3

    alt = sqlite3.connect(db)
    alt.executescript(retourenakte.SCHEMA.replace("    geliefert_am    TEXT,\n", ""))
    alt.close()

    angelegt = retourenakte.anlegen(zalando_retoure(), "test", db_path=db)
    assert angelegt.geliefert_am == date(2026, 10, 28)
