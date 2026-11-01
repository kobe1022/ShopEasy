"""Consumer Kundeninfo: simulierte Status-Mail im Log. Zustaendig: Muhammed.

TODO: bei kundenrelevanten Events eine Status-Mail ins Log schreiben (KPI K14),
Mailtext je Event-Typ. Doppelt zugestellte Events ignoriert `shared.broker.consume`.
"""

from loguru import logger

from shopeasy.shared import retourenakte
from shopeasy.shared.broker import consume
from shopeasy.shared.events import Event, EventType, parse_payload

# Betreff und Text je Event-Typ. Platzhalter in {} werden mit den Feldern aus
# dem Payload gefuellt (z.B. {tracking_nr}), {retouren_id} gibt es immer.
MAIL_TEXTE: dict[EventType, tuple[str, str]] = {
    EventType.RETOURE_REGISTRIERT: (
        "Wir haben deine Retoure erhalten",
        (
            "deine Retoure {retouren_id} ist bei uns angemeldet. "
            "Das Ruecksendelabel bekommst du in einer eigenen Mail."
        ),
    ),
    EventType.RETOURE_ABGELEHNT: (
        "Deine Retoure wurde abgelehnt",
        (
            "leider koennen wir deine Retoure {retouren_id} nicht annehmen. "
            "Grund: {grund}."
        ),
    ),
    EventType.LABEL_BEREITGESTELLT: (
        "Dein Ruecksendelabel ist da",
        (
            "fuer deine Retoure {retouren_id} steht das Label bereit "
            "({versanddienstleister}, Sendungsnummer {tracking_nr})."
        ),
    ),
    EventType.RUECKSENDUNG_UNTERWEGS: (
        "Dein Paket ist unterwegs",
        (
            "dein Paket zur Retoure {retouren_id} ist unterwegs zu uns "
            "(Sendungsnummer {tracking_nr})."
        ),
    ),
    EventType.WARE_EINGEGANGEN: (
        "Dein Paket ist bei uns angekommen",
        (
            "deine Ruecksendung {retouren_id} ist im Lager eingegangen. "
            "Wir pruefen die Ware jetzt."
        ),
    ),
    EventType.RETOURE_ANGENOMMEN: (
        "Deine Retoure wurde angenommen",
        (
            "die Pruefung deiner Retoure {retouren_id} ist abgeschlossen, "
            "wir nehmen sie an. Die Erstattung folgt."
        ),
    ),
    EventType.ERSTATTUNG_ABGESCHLOSSEN: (
        "Deine Erstattung ist veranlasst",
        (
            "fuer deine Retoure {retouren_id} erstatten wir dir {betrag:.2f} EUR "
            "(Art: {art})."
        ),
    ),
    EventType.RETOURE_STORNIERT: (
        "Deine Retoure wurde storniert",
        "deine Retoure {retouren_id} ist storniert. Grund: {grund}.",
    ),
}


def mail_inhalt(event: Event) -> tuple[str, str]:
    """Liefert Betreff und Text der Status-Mail fuer ein Event.

    Der Payload wird mit `parse_payload` geprueft; passt er nicht zum Event-Typ,
    gibt es einen Fehler und die Nachricht landet in der Dead-Letter-Queue.
    """
    betreff, vorlage = MAIL_TEXTE[event.event_type]
    felder = parse_payload(event).model_dump()
    text = vorlage.format(retouren_id=event.retouren_id, **felder)
    return betreff, text


def empfaenger(retouren_id: str) -> str:
    """Holt die Mail-Adresse der Kundin aus der Retourenakte."""
    retoure = retourenakte.holen(retouren_id)
    if retoure is None:
        raise LookupError(f"Retoure {retouren_id} nicht in der Retourenakte")
    return retoure.kunde_email


def handle(event: Event) -> None:
    logger.info("Kundeninfo: {} fuer {}", event.event_type.value, event.retouren_id)


if __name__ == "__main__":
    consume("kundeninfo", handle)
