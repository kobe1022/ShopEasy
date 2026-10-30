"""Consumer Event-Log: schreibt jedes Event fuer Process Mining. Zustaendig: Muhammed.

TODO: jedes Event als Zeile (Fall-ID = retouren_id, Aktivitaet = event_type,
Zeitstempel) in CSV oder DB schreiben; das ist die Datenbasis fuer Sprint 3
(Celonis) und die KPI-Berechnung. Idempotenz ueber event_id.
"""

from loguru import logger

from shopeasy.shared.broker import consume
from shopeasy.shared.events import Event

# Spalten im Process-Mining-Format: Fall-ID, Aktivitaet, Zeitstempel (+ Zusatzinfos)
COLUMNS = ["case_id", "activity", "timestamp", "event_id", "source"]


def to_row(event: Event) -> list[str]:
    """Wandelt ein Event in eine CSV-Zeile um (Reihenfolge wie COLUMNS)."""
    return [
        event.retouren_id,
        event.event_type.value,
        event.timestamp,
        event.event_id,
        event.source,
    ]


def handle(event: Event) -> None:
    logger.info(
        "Event-Log: {};{};{}",
        event.retouren_id,
        event.event_type.value,
        event.timestamp,
    )


if __name__ == "__main__":
    consume("eventlog", handle)
