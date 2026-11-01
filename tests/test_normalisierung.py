"""Tests fuer die Normalisierung der Marktplatz-Formate (Issue #9)."""

from datetime import date

import pytest

from shopeasy.marketplace_mock.formate import ZalandoReturn
from shopeasy.marketplace_mock.testdaten import amazon_testdaten, zalando_testdaten
from shopeasy.return_service.artikelstamm import UnbekannteEAN, sku_fuer_ean
from shopeasy.return_service.normalisierung import (
    MeldungNichtUebersetzbar,
    amazon_zu_neue_retoure,
    uebersetzen,
    zalando_zu_neue_retoure,
)
from shopeasy.shared.models import Kanal


def test_artikelstamm():
    assert sku_fuer_ean("4012345000017") == "PULLI-BLAU-M"
    with pytest.raises(UnbekannteEAN):
        sku_fuer_ean("9999999999999")


def test_amazon():
    retoure = amazon_zu_neue_retoure(amazon_testdaten()[0])

    assert retoure.kanal == Kanal.AMAZON
    assert retoure.externe_id == "AMZ-RET-001001"
    assert retoure.bestell_nr == "ORD-100234"
    assert retoure.kunde_email == "kundin@example.com"
    assert retoure.grund_text == "Zu klein: Faellt klein aus"
    assert [(a.sku, a.menge) for a in retoure.artikel] == [("PULLI-BLAU-M", 1)]
    assert retoure.gemeldet_am == date(2026, 10, 28)
    assert retoure.geliefert_am == date(2026, 10, 20)


def test_amazon_ohne_kommentar():
    retoure = amazon_zu_neue_retoure(amazon_testdaten()[1])
    assert retoure.grund_text == "Gefaellt nicht / nicht mehr gewuenscht"


def test_zalando():
    retoure = zalando_zu_neue_retoure(zalando_testdaten()[0])

    assert retoure.kanal == Kanal.ZALANDO
    assert retoure.externe_id == "ZRET-2026-001001"
    assert retoure.bestell_nr == "ORD-100301"
    assert retoure.kunde_email == "max@example.org"
    assert retoure.grund_text == "Gefaellt nicht: Farbe anders als auf dem Foto"
    # EAN -> SKU ueber den Artikelstamm, Datum TT.MM.JJJJ -> date
    assert [(a.sku, a.menge) for a in retoure.artikel] == [("SHIRT-WEISS-L", 1)]
    assert retoure.gemeldet_am == date(2026, 10, 29)
    assert retoure.geliefert_am == date(2026, 10, 22)


def test_zalando_unklarer_freitext_bleibt_unveraendert():
    """Code 99: der Freitext geht unveraendert an den KI-Agenten (Sprint 5)."""
    meldung = zalando_testdaten()[1]
    retoure = zalando_zu_neue_retoure(meldung)
    assert retoure.grund_text == meldung.reason.text


def test_zalando_unbekannte_ean():
    meldung = zalando_testdaten()[0]
    meldung.articles[0].ean = "9999999999999"
    with pytest.raises(UnbekannteEAN):
        zalando_zu_neue_retoure(meldung)


def test_vielretournierer_kanaluebergreifend_erkennbar():
    """Erst das einheitliche Modell macht die gleiche Kundin sichtbar (S5)."""
    retouren = [amazon_zu_neue_retoure(m) for m in amazon_testdaten()] + [
        zalando_zu_neue_retoure(m) for m in zalando_testdaten()
    ]
    vielretournierer = [
        r for r in retouren if r.kunde_email == "viel.retournierer@example.com"
    ]
    assert len(vielretournierer) == 3
    assert {r.kanal for r in vielretournierer} == {Kanal.AMAZON, Kanal.ZALANDO}


# --- uebersetzen: ein einheitlicher Fehlerfall ------------------------------


def test_uebersetzen_gueltige_meldung():
    retoure = uebersetzen("amazon", amazon_testdaten()[0])
    assert retoure.externe_id == "AMZ-RET-001001"


def test_uebersetzen_ungueltige_email():
    meldung = amazon_testdaten()[0].model_copy(update={"buyerEmail": "keine-mail"})
    with pytest.raises(MeldungNichtUebersetzbar, match="kunde_email"):
        uebersetzen("amazon", meldung)


def test_uebersetzen_unmoegliches_datum():
    daten = zalando_testdaten()[0].model_dump()
    daten["announced_on"] = "31.02.2026"
    with pytest.raises(MeldungNichtUebersetzbar, match="31.02.2026"):
        uebersetzen("zalando", ZalandoReturn(**daten))


def test_uebersetzen_unbekannte_ean():
    daten = zalando_testdaten()[0].model_dump()
    daten["articles"][0]["ean"] = "9999999999999"
    with pytest.raises(MeldungNichtUebersetzbar, match="9999999999999"):
        uebersetzen("zalando", ZalandoReturn(**daten))


def test_uebersetzen_falsches_format():
    with pytest.raises(MeldungNichtUebersetzbar, match="zalando-Format"):
        uebersetzen("zalando", amazon_testdaten()[0])
