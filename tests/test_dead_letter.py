"""Tests fuer die Dead-Letter-Queue (Issue #22).

Eine kaputte Nachricht soll in `retouren.dlq` landen, statt verloren zu gehen.
RabbitMQ macht das selbst, wenn der Consumer die Nachricht mit Nack ohne
Requeue ablehnt. Hier wird geprueft, dass der Consumer genau das tut. RabbitMQ
muss dafuer nicht laufen: ein Fake-Channel merkt sich nur Ack und Nack.
"""

import pytest

from shopeasy.consumers import eventlog
from shopeasy.shared import broker, config
from shopeasy.shared.events import (
    Event,
    EventType,
    PruefungAbgeschlossenPayload,
    build_event,
)
from shopeasy.shared.models import Zustand


class FakeChannel:
    """Merkt sich, welche Nachricht bestaetigt (Ack) oder abgelehnt (Nack) wurde."""

    def __init__(self) -> None:
        self.acks: list[int] = []
        self.nacks: list[tuple[int, bool]] = []

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue=True):
        self.nacks.append((delivery_tag, requeue))


@pytest.fixture
def store(tmp_path):
    return broker.VerarbeiteteEvents(tmp_path / "verarbeitet.db")


def gutes_event() -> Event:
    return build_event(
        EventType.PRUEFUNG_ABGESCHLOSSEN,
        "RET-2026-000001",
        "test",
        PruefungAbgeschlossenPayload(condition=Zustand.NEUWERTIG, inspector="lager"),
    )


def test_kaputtes_json_landet_in_der_dead_letter_queue(store):
    channel = FakeChannel()

    ok = broker.bestaetigen(channel, 1, "eventlog", b"{kein json", print, store)

    assert ok is False
    assert channel.nacks == [(1, False)]  # Nack OHNE Requeue -> retouren.dlq
    assert channel.acks == []


def test_falscher_payload_landet_in_der_dead_letter_queue(store, monkeypatch, tmp_path):
    # Event-Typ "pruefung.abgeschlossen", aber im Payload fehlt "condition"
    monkeypatch.setattr(config, "EVENTLOG_PATH", str(tmp_path / "eventlog.csv"))
    kaputt = Event(
        event_type=EventType.PRUEFUNG_ABGESCHLOSSEN,
        retouren_id="RET-2026-000001",
        source="test",
        payload={"inspector": "lager"},
    )
    channel = FakeChannel()

    ok = broker.bestaetigen(
        channel,
        7,
        "eventlog",
        kaputt.model_dump_json().encode(),
        eventlog.handle,
        store,
    )

    assert ok is False
    assert channel.nacks == [(7, False)]
    assert not (tmp_path / "eventlog.csv").exists()  # nichts ins Event-Log


def test_abgelehnte_nachricht_wird_nicht_als_verarbeitet_gemerkt(store):
    event = gutes_event()

    def handler_mit_fehler(_event):
        raise RuntimeError("Datenbank weg")

    broker.bestaetigen(
        FakeChannel(),
        1,
        "eventlog",
        event.model_dump_json().encode(),
        handler_mit_fehler,
        store,
    )

    assert not store.bereits_verarbeitet("eventlog", event.event_id)
