"""Tests fuer die Dead-Letter-Queue (Issue #22).

Eine kaputte Nachricht soll in `retouren.dlq` landen, statt verloren zu gehen.
RabbitMQ macht das selbst, wenn der Consumer die Nachricht mit Nack ohne
Requeue ablehnt. Hier wird geprueft, dass der Consumer genau das tut. RabbitMQ
muss dafuer nicht laufen: ein Fake-Channel merkt sich nur Ack und Nack.
"""

import pytest

from shopeasy.shared import broker
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
