"""Tests fuer den Mock-Marktplatz (Issues #6, #7, #8)."""

import pytest
from fastapi.testclient import TestClient

from shopeasy.marketplace_mock.app import app, zuruecksetzen


@pytest.fixture
def client():
    zuruecksetzen()  # jeder Test startet mit den frischen Testdaten
    return TestClient(app)


def test_neue_meldungen_je_marktplatz(client):
    amazon = client.get("/amazon/returns", params={"status": "new"}).json()
    zalando = client.get("/zalando/returns").json()  # status=new ist Standard

    assert len(amazon) == 3
    assert len(zalando) == 4
    # unterschiedliche Formate je Marktplatz
    assert {"returnId", "buyerEmail", "items"} <= amazon[0].keys()
    assert {"id", "order", "customer", "articles"} <= zalando[0].keys()


@pytest.mark.parametrize("url", ["/ebay/returns", "/amazon/returns?status=quatsch"])
def test_ungueltige_anfragen(client, url):
    assert client.get(url).status_code == 422


def test_einzelmeldung_und_404(client):
    meldung = client.get("/amazon/returns/AMZ-RET-001001")
    assert meldung.status_code == 200
    assert meldung.json()["orderId"] == "ORD-100234"

    # jeder Marktplatz kennt nur seine eigenen Meldungen
    assert client.get("/amazon/returns/ZRET-2026-001001").status_code == 404


def test_quittieren_entfernt_aus_neuen_meldungen(client):
    antwort = client.post("/zalando/returns/ZRET-2026-001001/ack")
    assert antwort.status_code == 200
    assert antwort.json()["state"] == "confirmed"

    neu = [m["id"] for m in client.get("/zalando/returns").json()]
    assert "ZRET-2026-001001" not in neu
    quittiert = client.get("/zalando/returns", params={"status": "acknowledged"})
    assert [m["id"] for m in quittiert.json()] == ["ZRET-2026-001001"]

    # idempotent: erneutes Quittieren schadet nicht
    assert client.post("/zalando/returns/ZRET-2026-001001/ack").status_code == 200


def test_quittieren_unbekannte_meldung(client):
    assert client.post("/amazon/returns/GIBT-ES-NICHT/ack").status_code == 404


def test_testfall_anlegen(client):
    neu = client.get("/amazon/returns/AMZ-RET-001001").json() | {
        "returnId": "AMZ-RET-009999"
    }
    antwort = client.post("/amazon/returns", json=neu)

    assert antwort.status_code == 201
    ids = [m["returnId"] for m in client.get("/amazon/returns").json()]
    assert "AMZ-RET-009999" in ids


def test_erneutes_senden_setzt_meldung_wieder_auf_neu(client):
    """Grundlage fuer den Dubletten-Testfall im Retouren-Service (#11)."""
    client.post("/amazon/returns/AMZ-RET-001001/ack")
    meldung = client.get("/amazon/returns/AMZ-RET-001001").json()
    assert meldung["status"] == "ACKNOWLEDGED"

    antwort = client.post("/amazon/returns", json=meldung)

    assert antwort.status_code == 201
    assert antwort.json()["status"] == "NEW"


def test_testfall_im_falschen_format(client):
    zalando = client.get("/zalando/returns/ZRET-2026-001001").json()
    assert client.post("/amazon/returns", json=zalando).status_code == 422
