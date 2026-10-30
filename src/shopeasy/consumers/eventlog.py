"""Consumer Event-Log: schreibt jedes Event fuer Process Mining. Zustaendig: Muhammed.

TODO: jedes Event als Zeile (Fall-ID = retouren_id, Aktivitaet = event_type,
Zeitstempel) in CSV oder DB schreiben; das ist die Datenbasis fuer Sprint 3
(Celonis) und die KPI-Berechnung. Idempotenz ueber event_id.
"""

from loguru import logger

from shopeasy.shared.broker import consume
from shopeasy.shared.events import Event


def handle(event: Event) -> None:
    logger.info(
        "Event-Log: {};{};{}",
        event.retouren_id,
        event.event_type.value,
        event.timestamp,
    )


if __name__ == "__main__":
    consume("eventlog", handle)
