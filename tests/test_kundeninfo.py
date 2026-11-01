"""Tests fuer den Kundeninfo-Consumer: Status-Mails (Issue #21, Tests #25)."""

import pytest

from shopeasy.consumers import kundeninfo
from shopeasy.shared import config, retourenakte
from shopeasy.shared.events import (
    ErstattungAbgeschlossenPayload,
    EventType,
    LabelBereitgestelltPayload,
    build_event,
)
from shopeasy.shared.models import Artikel, Kanal, NeueRetoure


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
