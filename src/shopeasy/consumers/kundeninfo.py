"""Consumer Kundeninfo: simulierte Status-Mail im Log. Zustaendig: Muhammed.

TODO: bei kundenrelevanten Events eine Status-Mail ins Log schreiben (KPI K14),
Mailtext je Event-Typ. Doppelt zugestellte Events ignoriert `shared.broker.consume`.
"""

from loguru import logger

from shopeasy.shared.broker import consume
from shopeasy.shared.events import Event


def handle(event: Event) -> None:
    logger.info("Kundeninfo: {} fuer {}", event.event_type.value, event.retouren_id)


if __name__ == "__main__":
    consume("kundeninfo", handle)
