"""Tests fuer die Endpunkte des Retouren-Service (Issues #10-#14).

Jeder Test bekommt eine eigene, leere Retourenakte. Der Message Broker und der
Marktplatz werden ersetzt, es muss also weder RabbitMQ noch der Mock laufen.
"""

import pytest
from fastapi.testclient import TestClient
from pika.exceptions import AMQPConnectionError

from shopeasy.marketplace_mock.formate import ZalandoReturn
from shopeasy.marketplace_mock.testdaten import amazon_testdaten, zalando_testdaten
from shopeasy.return_service import marktplatz_client
from shopeasy.return_service.app import app
from shopeasy.shared import broker, config
from shopeasy.shared.events import EventType

WEBSHOP_ANMELDUNG = {
    "bestell_nr": "ORD-100300",
    "kunde_email": "max@example.org",
    "grund_text": "Farbe gefaellt nicht",
    "artikel": [{"sku": "SHIRT-WEISS-L", "menge": 1}],
}


@pytest.fixture
def events(monkeypatch, tmp_path):
    """Eigene Akte je Test; gesendete Events landen in einer Liste."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "retourenakte.db"))
    gesendet = []
    monkeypatch.setattr(broker, "publish", gesendet.append)
    return gesendet


@pytest.fixture
def client(events):
    return TestClient(app)


@pytest.fixture
def marktplatz(monkeypatch):
    """Ersetzt den Mock-Marktplatz: offene Meldungen je Marktplatz."""
    offen = {
        "amazon": {m.returnId: m for m in amazon_testdaten()},
        "zalando": {m.id: m for m in zalando_testdaten()},
    }
    monkeypatch.setattr(
        marktplatz_client,
        "hole_neue_meldungen",
        lambda marketplace, base_url=None: list(offen[marketplace].values()),
    )
    monkeypatch.setattr(
        marktplatz_client,
        "quittieren",
        lambda marketplace, meldungs_id, base_url=None: offen[marketplace].pop(
            meldungs_id
        ),
    )
    return offen


# --- Webshop und Abfrage (#10, #14) -----------------------------------------


def test_webshop_anmeldung_anlegen_und_abfragen(client, events):
    angelegt = client.post("/returns", json=WEBSHOP_ANMELDUNG)

    assert angelegt.status_code == 201
    retoure = angelegt.json()
    assert retoure["retouren_id"].startswith("RET-")
    assert retoure["kanal"] == "WEBSHOP"
    assert retoure["status"] == "REGISTRIERT"

    abfrage = client.get(f"/returns/{retoure['retouren_id']}")
    assert abfrage.status_code == 200
    historie = abfrage.json()["historie"]
    assert [e["status"] for e in historie] == ["REGISTRIERT"]

    assert [e.event_type for e in events] == [EventType.RETOURE_REGISTRIERT]
    assert events[0].payload["kunde_email"] == "max@example.org"


def test_webshop_ungueltige_anmeldung(client, events):
    falsch = WEBSHOP_ANMELDUNG | {"kunde_email": "keine-mail"}
    assert client.post("/returns", json=falsch).status_code == 422
    assert events == []


def test_unbekannte_retoure(client):
    assert client.get("/returns/RET-2026-999999").status_code == 404


# --- Webhook und Dubletten (#11) --------------------------------------------


def test_marktplatz_meldung_und_dublette(client, events):
    meldung = amazon_testdaten()[0].model_dump(mode="json")

    erste = client.post("/returns/marketplace/amazon", json=meldung)
    zweite = client.post("/returns/marketplace/amazon", json=meldung)

    assert erste.status_code == 201
    assert erste.json()["externe_id"] == "AMZ-RET-001001"
    assert zweite.status_code == 409
    assert zweite.json()["detail"]["retouren_id"] == erste.json()["retouren_id"]
    assert len(events) == 1  # fuer die Dublette kein zweites Event


def test_marktplatz_meldung_im_falschen_format(client):
    zalando = zalando_testdaten()[0].model_dump(mode="json")
    assert client.post("/returns/marketplace/amazon", json=zalando).status_code == 422


def test_marktplatz_meldung_mit_unbekanntem_artikel(client, events):
    meldung = zalando_testdaten()[0]
    meldung.articles[0].ean = "9999999999999"

    antwort = client.post(
        "/returns/marketplace/zalando", json=meldung.model_dump(mode="json")
    )

    assert antwort.status_code == 422
    assert "Artikelstamm" in antwort.json()["detail"]
    assert events == []


# --- Polling (#13) ----------------------------------------------------------


def test_polling_legt_an_und_quittiert(client, events, marktplatz):
    ergebnis = client.post("/returns/poll").json()

    assert len(ergebnis["angelegt"]) == 7
    assert ergebnis["dubletten"] == []
    assert marktplatz == {"amazon": {}, "zalando": {}}  # alles quittiert
    assert len(events) == 7

    # zweiter Lauf: nichts Neues mehr da
    assert client.post("/returns/poll").json()["angelegt"] == []


def test_polling_erneut_gesendete_meldung_ist_dublette(client, events, marktplatz):
    erster_lauf = client.post("/returns/poll").json()
    bekannte_id = erster_lauf["angelegt"][0]["retouren_id"]

    marktplatz["amazon"]["AMZ-RET-001001"] = amazon_testdaten()[0]  # erneut gesendet
    zweiter_lauf = client.post("/returns/poll").json()

    assert [d["retouren_id"] for d in zweiter_lauf["dubletten"]] == [bekannte_id]
    assert marktplatz["amazon"] == {}  # Dublette wurde trotzdem quittiert
    assert len(events) == 7


def test_polling_unbekannter_artikel_bleibt_offen(client, marktplatz):
    marktplatz["zalando"]["ZRET-2026-001004"].articles[0].ean = "9999999999999"

    ergebnis = client.post("/returns/poll").json()

    assert [m["externe_id"] for m in ergebnis["manuell_pruefen"]] == [
        "ZRET-2026-001004"
    ]
    assert list(marktplatz["zalando"]) == ["ZRET-2026-001004"]  # nicht quittiert


def test_polling_marktplatz_nicht_erreichbar(client, monkeypatch):
    def nicht_erreichbar(marketplace, base_url=None):
        raise marktplatz_client.MarktplatzNichtErreichbar(marketplace)

    monkeypatch.setattr(marktplatz_client, "hole_neue_meldungen", nicht_erreichbar)

    ergebnis = client.post("/returns/poll").json()
    assert ergebnis["nicht_erreichbar"] == ["amazon", "zalando"]


# --- Event bei Broker-Ausfall (#12) -----------------------------------------


def test_retoure_bleibt_angelegt_wenn_broker_nicht_erreichbar(client, monkeypatch):
    def broker_aus(event):
        raise AMQPConnectionError("Broker nicht erreichbar")

    monkeypatch.setattr(broker, "publish", broker_aus)

    antwort = client.post("/returns", json=WEBSHOP_ANMELDUNG)

    assert antwort.status_code == 201
    retouren_id = antwort.json()["retouren_id"]
    assert client.get(f"/returns/{retouren_id}").status_code == 200


# --- Ungueltige Marktplatz-Meldungen (#9, #11, #13) -------------------------


def amazon_mit_ungueltiger_email():
    return amazon_testdaten()[0].model_copy(
        update={"returnId": "AMZ-RET-009001", "buyerEmail": "keine-mail"}
    )


def zalando_mit_unmoeglichem_datum():
    daten = zalando_testdaten()[0].model_dump()
    daten["id"] = "ZRET-2026-009001"
    daten["order"]["delivered_on"] = "99.99.2026"
    return ZalandoReturn(**daten)


def test_webhook_ungueltige_email_ist_422(client, events):
    antwort = client.post(
        "/returns/marketplace/amazon",
        json=amazon_mit_ungueltiger_email().model_dump(mode="json"),
    )

    assert antwort.status_code == 422
    assert "kunde_email" in antwort.json()["detail"]
    assert events == []


def test_webhook_unmoegliches_datum_ist_422(client, events):
    antwort = client.post(
        "/returns/marketplace/zalando",
        json=zalando_mit_unmoeglichem_datum().model_dump(mode="json"),
    )

    assert antwort.status_code == 422
    assert "99.99.2026" in antwort.json()["detail"]
    assert events == []


def test_polling_ungueltige_meldungen_blockieren_die_anderen_nicht(
    client, marktplatz, events
):
    schlecht_amazon = amazon_mit_ungueltiger_email()
    schlecht_zalando = zalando_mit_unmoeglichem_datum()
    marktplatz["amazon"][schlecht_amazon.returnId] = schlecht_amazon
    marktplatz["zalando"][schlecht_zalando.id] = schlecht_zalando

    antwort = client.post("/returns/poll")

    assert antwort.status_code == 200
    ergebnis = antwort.json()
    assert sorted(m["externe_id"] for m in ergebnis["manuell_pruefen"]) == [
        "AMZ-RET-009001",
        "ZRET-2026-009001",
    ]
    assert "kunde_email" in ergebnis["manuell_pruefen"][0]["hinweis"]
    assert len(ergebnis["angelegt"]) == 7  # alle gueltigen Testmeldungen
    assert len(events) == 7
    # die ungueltigen bleiben unquittiert beim Marktplatz liegen
    assert list(marktplatz["amazon"]) == ["AMZ-RET-009001"]
    assert list(marktplatz["zalando"]) == ["ZRET-2026-009001"]
