"""Tests fuer den Broker-Helper: Idempotenz (Issue #5) und Verbindungsaufbau."""

import pika
import pytest
from pika.exceptions import AMQPConnectionError, StreamLostError

from shopeasy.shared import broker
from shopeasy.shared.events import (
    Event,
    EventType,
    PruefungAbgeschlossenPayload,
    build_event,
)
from shopeasy.shared.models import Zustand


@pytest.fixture
def store(tmp_path):
    return broker.VerarbeiteteEvents(tmp_path / "verarbeitet.db")


def neues_event() -> Event:
    return build_event(
        EventType.PRUEFUNG_ABGESCHLOSSEN,
        "RET-2026-000001",
        "test",
        PruefungAbgeschlossenPayload(condition=Zustand.NEUWERTIG, inspector="lager"),
    )


def als_nachricht(event: Event) -> bytes:
    return event.model_dump_json().encode()


# --- Idempotenz (#5) --------------------------------------------------------


def test_gleiches_event_wird_nur_einmal_verarbeitet(store):
    gesehen = []
    nachricht = als_nachricht(neues_event())

    erste = broker.verarbeiten("eventlog", nachricht, gesehen.append, store)
    zweite = broker.verarbeiten("eventlog", nachricht, gesehen.append, store)

    assert (erste, zweite) == (True, False)
    assert len(gesehen) == 1


def test_verschiedene_events_werden_beide_verarbeitet(store):
    gesehen = []

    broker.verarbeiten("eventlog", als_nachricht(neues_event()), gesehen.append, store)
    broker.verarbeiten("eventlog", als_nachricht(neues_event()), gesehen.append, store)

    assert len(gesehen) == 2


def test_jede_queue_verarbeitet_das_event_einmal(store):
    """Kundeninfo und Event-Log bekommen dasselbe Event, beide muessen es sehen."""
    kundeninfo, eventlog = [], []
    nachricht = als_nachricht(neues_event())

    broker.verarbeiten("kundeninfo", nachricht, kundeninfo.append, store)
    broker.verarbeiten("eventlog", nachricht, eventlog.append, store)

    assert len(kundeninfo) == len(eventlog) == 1


def test_fehler_im_handler_wird_nicht_gemerkt(store):
    nachricht = als_nachricht(neues_event())

    def kaputt(event):
        raise RuntimeError("Handler fehlgeschlagen")

    with pytest.raises(RuntimeError):
        broker.verarbeiten("eventlog", nachricht, kaputt, store)

    gesehen = []
    assert broker.verarbeiten("eventlog", nachricht, gesehen.append, store) is True
    assert len(gesehen) == 1


def test_gemerkte_events_ueberleben_einen_neustart(tmp_path):
    pfad = tmp_path / "verarbeitet.db"
    event = neues_event()
    broker.VerarbeiteteEvents(pfad).merken("eventlog", event.event_id)

    assert broker.VerarbeiteteEvents(pfad).bereits_verarbeitet(
        "eventlog", event.event_id
    )


def test_ungueltige_nachricht_wirft(store):
    with pytest.raises(ValueError):
        broker.verarbeiten("eventlog", b"kaputt", lambda e: None, store)


# --- Verbindungsaufbau ------------------------------------------------------


def test_connect_wiederholt_bis_der_broker_bereit_ist(monkeypatch):
    versuche = []

    def verbinden(parameter):
        versuche.append(parameter)
        if len(versuche) < 3:
            raise StreamLostError("Transport indicated EOF")
        return "verbindung"

    monkeypatch.setattr(pika, "BlockingConnection", verbinden)
    monkeypatch.setattr(broker.time, "sleep", lambda sekunden: None)

    assert broker.connect(versuche=5, pause=0) == "verbindung"
    assert len(versuche) == 3


def test_connect_gibt_nach_den_versuchen_auf(monkeypatch):
    versuche = []

    def verbinden(parameter):
        versuche.append(parameter)
        raise AMQPConnectionError("nicht erreichbar")

    monkeypatch.setattr(pika, "BlockingConnection", verbinden)
    monkeypatch.setattr(broker.time, "sleep", lambda sekunden: None)

    with pytest.raises(AMQPConnectionError):
        broker.connect(versuche=3, pause=0)
    assert len(versuche) == 3


def test_connect_ohne_wiederholung_scheitert_sofort(monkeypatch):
    def verbinden(parameter):
        raise AMQPConnectionError("nicht erreichbar")

    monkeypatch.setattr(pika, "BlockingConnection", verbinden)

    with pytest.raises(AMQPConnectionError):
        broker.connect()
