"""Tests fuer den HTTP-Client zum Marktplatz: kaputte Antworten (Issue #13)."""

import httpx
import pytest

from shopeasy.marketplace_mock.testdaten import amazon_testdaten
from shopeasy.return_service import marktplatz_client
from shopeasy.return_service.marktplatz_client import (
    MarktplatzNichtErreichbar,
    hole_neue_meldungen,
)


def marktplatz_antwortet(monkeypatch, **antwort):
    """Ersetzt den HTTP-Client durch einen, der immer dieselbe Antwort liefert."""
    monkeypatch.setattr(
        marktplatz_client,
        "_client",
        lambda base_url: httpx.Client(
            transport=httpx.MockTransport(lambda anfrage: httpx.Response(**antwort)),
            base_url="http://marktplatz",
        ),
    )


def test_gueltige_antwort(monkeypatch):
    daten = [m.model_dump(mode="json") for m in amazon_testdaten()]
    marktplatz_antwortet(monkeypatch, status_code=200, json=daten)

    assert len(hole_neue_meldungen("amazon")) == 3


def test_kaputte_meldung_blockiert_die_anderen_nicht(monkeypatch):
    daten = [m.model_dump(mode="json") for m in amazon_testdaten()]
    daten[1] = {"returnId": "AMZ-KAPUTT"}  # Pflichtfelder fehlen
    marktplatz_antwortet(monkeypatch, status_code=200, json=daten)

    meldungen = hole_neue_meldungen("amazon")

    assert [m.returnId for m in meldungen] == ["AMZ-RET-001001", "AMZ-RET-001003"]


@pytest.mark.parametrize(
    "antwort",
    [
        {"status_code": 200, "content": b"das ist kein JSON"},
        {"status_code": 200, "json": {"keine": "liste"}},
        {"status_code": 500},
    ],
)
def test_unbrauchbare_antwort_ist_nicht_erreichbar(monkeypatch, antwort):
    marktplatz_antwortet(monkeypatch, **antwort)

    with pytest.raises(MarktplatzNichtErreichbar):
        hole_neue_meldungen("amazon")
