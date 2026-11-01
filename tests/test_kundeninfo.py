"""Tests fuer den Kundeninfo-Consumer: Status-Mails (Issue #21, Tests #25)."""

import pytest
from loguru import logger

from shopeasy.consumers import kundeninfo
from shopeasy.shared import config, retourenakte
from shopeasy.shared.events import (
    ErstattungAbgeschlossenPayload,
    EventType,
    LabelBereitgestelltPayload,
    PruefungAbgeschlossenPayload,
    build_event,
)
from shopeasy.shared.models import Artikel, Kanal, NeueRetoure, Zustand


@pytest.fixture
def retoure(tmp_path, monkeypatch):
    """Legt eine Retoure in einer eigenen, leeren Retourenakte an."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "retourenakte.db"))
    return retourenakte.anlegen(
        NeueRetoure(
            kanal=Kanal.WEBSHOP,
            bestell_nr="ORD-100234",
            kunde_email="kundin@example.com",
            grund_text="Zu gross",
            artikel=[Artikel(sku="SKU-1")],
        ),
        quelle="test",
    )


@pytest.fixture
def log():
    """Sammelt alle Log-Zeilen, damit man die simulierte Mail pruefen kann."""
    zeilen: list[str] = []
    sink_id = logger.add(zeilen.append, format="{message}")
    yield zeilen
    logger.remove(sink_id)


def test_mailtext_enthaelt_daten_aus_dem_payload(retoure):
    event = build_event(
        EventType.LABEL_BEREITGESTELLT,
        retoure.retouren_id,
        "test",
        LabelBereitgestelltPayload(tracking_nr="T-123", versanddienstleister="DHL"),
    )

    betreff, text = kundeninfo.mail_inhalt(event)

    assert betreff == "Dein Ruecksendelabel ist da"
    assert retoure.retouren_id in text
    assert "DHL" in text and "T-123" in text


def test_erstattungsbetrag_mit_zwei_nachkommastellen(retoure):
    event = build_event(
        EventType.ERSTATTUNG_ABGESCHLOSSEN,
        retoure.retouren_id,
        "test",
        ErstattungAbgeschlossenPayload(betrag=19.9, art="ZAHLUNG"),
    )

    _, text = kundeninfo.mail_inhalt(event)

    assert "19.90 EUR" in text


def test_empfaenger_kommt_aus_der_retourenakte(retoure):
    assert kundeninfo.empfaenger(retoure.retouren_id) == "kundin@example.com"


def test_unbekannte_retoure_wirft_fehler(retoure):
    # Der Fehler sorgt im Consumer fuer ein Nack -> Dead-Letter-Queue
    with pytest.raises(LookupError):
        kundeninfo.empfaenger("RET-2026-999999")


def test_handle_schreibt_status_mail_ins_log(retoure, log):
    event = build_event(
        EventType.LABEL_BEREITGESTELLT,
        retoure.retouren_id,
        "test",
        LabelBereitgestelltPayload(tracking_nr="T-123", versanddienstleister="DHL"),
    )

    kundeninfo.handle(event)

    mails = [z for z in log if z.startswith("Status-Mail an kundin@example.com")]
    assert len(mails) == 1
    assert "Dein Ruecksendelabel ist da" in mails[0]


def test_keine_mail_fuer_interne_events(retoure, log):
    event = build_event(
        EventType.PRUEFUNG_ABGESCHLOSSEN,
        retoure.retouren_id,
        "test",
        PruefungAbgeschlossenPayload(condition=Zustand.NEUWERTIG, inspector="lager"),
    )

    kundeninfo.handle(event)

    assert not any(z.startswith("Status-Mail") for z in log)
