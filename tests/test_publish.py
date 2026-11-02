"""Tests fuers Senden von Statusmeldungen ueber `broker.publish` (Issue #25).

RabbitMQ muss nicht laufen: eine Fake-Verbindung merkt sich, was gesendet wird.
"""

import pika

from shopeasy.shared import broker
from shopeasy.shared.events import (
    Event,
    EventType,
    RuecksendungUnterwegsPayload,
    build_event,
)


class FakeChannel:
    def __init__(self) -> None:
        self.gesendet: list[dict] = []

    def exchange_declare(self, *args, **kwargs):
        pass

    def queue_declare(self, *args, **kwargs):
        pass

    def queue_bind(self, *args, **kwargs):
        pass

    def basic_publish(self, exchange, routing_key, body, properties):
        self.gesendet.append(
            {
                "exchange": exchange,
                "routing_key": routing_key,
                "body": body,
                "properties": properties,
            }
        )


class FakeConnection:
    def __init__(self) -> None:
        self.kanal = FakeChannel()

    def channel(self):
        return self.kanal

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def gesendete_nachrichten(monkeypatch) -> list[dict]:
    verbindung = FakeConnection()
    monkeypatch.setattr(broker, "connect", lambda *args, **kwargs: verbindung)
    return verbindung.kanal.gesendet


def neues_event() -> Event:
    return build_event(
        EventType.RUECKSENDUNG_UNTERWEGS,
        "RET-2026-000001",
        "test",
        RuecksendungUnterwegsPayload(tracking_nr="T-123"),
    )


def test_event_geht_mit_seinem_typ_als_routing_key_an_den_exchange(monkeypatch):
    gesendet = gesendete_nachrichten(monkeypatch)

    broker.publish(neues_event())

    assert len(gesendet) == 1
    assert gesendet[0]["exchange"] == broker.EXCHANGE
    assert gesendet[0]["routing_key"] == "ruecksendung.unterwegs"


def test_nachricht_ist_persistent_und_traegt_die_event_id(monkeypatch):
    gesendet = gesendete_nachrichten(monkeypatch)
    event = neues_event()

    broker.publish(event)

    properties = gesendet[0]["properties"]
    assert properties.delivery_mode == pika.DeliveryMode.Persistent.value
    assert properties.message_id == event.event_id


def test_gesendete_nachricht_kommt_beim_empfaenger_gleich_an(monkeypatch):
    gesendet = gesendete_nachrichten(monkeypatch)
    event = neues_event()

    broker.publish(event)

    # Senden und Empfangen passen zusammen: der Consumer liest genau dieses Event
    assert Event.model_validate_json(gesendet[0]["body"]) == event
