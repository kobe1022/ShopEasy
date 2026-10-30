from fastapi.testclient import TestClient

from shopeasy.marketplace_mock.app import app as marketplace_app
from shopeasy.return_service.app import app as return_app
from shopeasy.shared.events import Event, EventType
from shopeasy.warehouse.v1 import warehouse_pb2


def test_event_roundtrip():
    event = Event(
        event_type=EventType.WARE_EINGEGANGEN,
        retouren_id="RET-2026-000123",
        source="warehouse-grpc",
        payload={"scanner_id": "LAGER-03"},
    )
    parsed = Event.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.schema_version == 1


def test_routing_keys_vollstaendig():
    assert len(EventType) == 9


def test_health_rest_services():
    for app in (marketplace_app, return_app):
        assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_proto_enum():
    assert warehouse_pb2.Condition.Value("NEUWERTIG") == 1
