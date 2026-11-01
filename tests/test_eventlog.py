"""Tests fuer den Event-Log-Consumer (Issue #4)."""

import csv

import pytest
from pydantic import ValidationError

from shopeasy.consumers import eventlog
from shopeasy.shared import config
from shopeasy.shared.events import (
    Event,
    EventType,
    PruefungAbgeschlossenPayload,
    build_event,
)
from shopeasy.shared.models import Zustand


def event(retouren_id="RET-2026-000001") -> Event:
    return build_event(
        EventType.PRUEFUNG_ABGESCHLOSSEN,
        retouren_id,
        "warehouse-grpc",
        PruefungAbgeschlossenPayload(condition=Zustand.GETRAGEN, inspector="lager"),
    )


def zeilen(pfad):
    with pfad.open(newline="", encoding="utf-8") as datei:
        return list(csv.reader(datei, delimiter=eventlog.DELIMITER))


def test_datei_bekommt_kopfzeile(tmp_path):
    pfad = tmp_path / "daten" / "eventlog.csv"

    eventlog.ensure_file(pfad)

    assert zeilen(pfad) == [eventlog.COLUMNS]


def test_event_wird_als_zeile_angehaengt(tmp_path):
    pfad = tmp_path / "eventlog.csv"
    erstes, zweites = event("RET-2026-000001"), event("RET-2026-000002")

    eventlog.append_event(erstes, pfad)
    eventlog.append_event(zweites, pfad)

    assert zeilen(pfad) == [
        eventlog.COLUMNS,
        [
            "RET-2026-000001",
            "pruefung.abgeschlossen",
            erstes.timestamp,
            erstes.event_id,
            "warehouse-grpc",
        ],
        [
            "RET-2026-000002",
            "pruefung.abgeschlossen",
            zweites.timestamp,
            zweites.event_id,
            "warehouse-grpc",
        ],
    ]


def test_handle_schreibt_in_den_konfigurierten_pfad(tmp_path, monkeypatch):
    pfad = tmp_path / "eventlog.csv"
    monkeypatch.setattr(eventlog, "EVENTLOG_PATH", str(pfad))

    eventlog.handle(event())

    assert len(zeilen(pfad)) == 2  # Kopfzeile + 1 Event


def test_ungueltiger_payload_wird_nicht_geloggt(tmp_path, monkeypatch):
    """Faellt in der Praxis in die Dead-Letter-Queue (siehe broker.consume)."""
    pfad = tmp_path / "eventlog.csv"
    monkeypatch.setattr(eventlog, "EVENTLOG_PATH", str(pfad))
    kaputt = Event(
        event_type=EventType.WARE_EINGEGANGEN,
        retouren_id="RET-2026-000001",
        source="test",
        payload={},
    )

    with pytest.raises(ValidationError):
        eventlog.handle(kaputt)
    assert not pfad.exists()


def test_standardpfad_ist_konfigurierbar():
    assert config.EVENTLOG_PATH.endswith("eventlog.csv")
