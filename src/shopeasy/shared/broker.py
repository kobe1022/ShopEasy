"""RabbitMQ-Anbindung: Topologie, Publish-Helper und Consumer-Schleife."""

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pika
from loguru import logger
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPConnectionError

from shopeasy.shared import config
from shopeasy.shared.events import Event

EXCHANGE = "retouren.status"
DEAD_LETTER_EXCHANGE = "retouren.dlx"
DEAD_LETTER_QUEUE = "retouren.dlq"

# Queue -> Routing-Keys; jeder Consumer hat eine eigene Queue (Publish/Subscribe).
QUEUES: dict[str, list[str]] = {
    "kundeninfo": [
        "retoure.registriert",
        "retoure.abgelehnt",
        "label.bereitgestellt",
        "ruecksendung.unterwegs",
        "ware.eingegangen",
        "retoure.angenommen",
        "erstattung.abgeschlossen",
        "retoure.storniert",
    ],
    "eventlog": ["#"],
}

# Ein Sender soll nicht lange blockieren, ein Consumer darf auf den Broker warten.
PUBLISH_VERSUCHE = 3
PUBLISH_PAUSE_SEKUNDEN = 1.0
CONSUME_VERSUCHE = 30
CONSUME_PAUSE_SEKUNDEN = 2.0


def connect(versuche: int = 1, pause: float = 2.0) -> pika.BlockingConnection:
    """Verbindet mit RabbitMQ und wiederholt es, falls der Broker noch startet.

    RabbitMQ meldet sich im Docker-Healthcheck schon, bevor der AMQP-Port
    Verbindungen annimmt; ohne Wiederholung scheitert ein frisch gestarteter
    Service oder Consumer genau in dieser Zeit.
    """
    versuch = 1
    while True:
        try:
            return pika.BlockingConnection(pika.URLParameters(config.RABBITMQ_URL))
        except (AMQPConnectionError, OSError) as fehler:
            if versuch >= versuche:
                raise
            logger.warning(
                "RabbitMQ nicht bereit ({}), Versuch {}/{}", fehler, versuch, versuche
            )
            versuch += 1
            time.sleep(pause)


def declare_topology(channel: BlockingChannel) -> None:
    """Legt Exchanges, Queues und Dead-Letter-Queue an (idempotent)."""
    channel.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(DEAD_LETTER_EXCHANGE, exchange_type="fanout", durable=True)
    channel.queue_declare(DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(DEAD_LETTER_QUEUE, DEAD_LETTER_EXCHANGE)
    for queue, routing_keys in QUEUES.items():
        channel.queue_declare(
            queue,
            durable=True,
            arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE},
        )
        for key in routing_keys:
            channel.queue_bind(queue, EXCHANGE, routing_key=key)


def publish(event: Event) -> None:
    """Publiziert ein Event persistent auf dem Topic-Exchange."""
    with connect(PUBLISH_VERSUCHE, PUBLISH_PAUSE_SEKUNDEN) as connection:
        channel = connection.channel()
        declare_topology(channel)
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=event.event_type.value,
            body=event.model_dump_json().encode(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=event.event_id,
            ),
        )
    logger.info("Event publiziert: {} {}", event.event_type.value, event.retouren_id)


class VerarbeiteteEvents:
    """Merkt sich je Queue, welche `event_id` schon verarbeitet wurde (Idempotenz).

    Der Broker stellt Nachrichten "mindestens einmal" zu. Kommt dasselbe Event
    ein zweites Mal (z.B. nach einem Verbindungsabbruch vor dem Ack), darf ein
    Consumer es nicht ein zweites Mal verarbeiten. Die Liste liegt in SQLite und
    bleibt damit auch nach einem Neustart erhalten.
    """

    def __init__(self, pfad: str | Path | None = None) -> None:
        self._pfad = Path(pfad or config.IDEMPOTENZ_DB)

    def _verbinden(self) -> sqlite3.Connection:
        self._pfad.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._pfad, timeout=10)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS verarbeitete_events ("
            " queue TEXT NOT NULL, event_id TEXT NOT NULL,"
            " verarbeitet_am TEXT NOT NULL, PRIMARY KEY (queue, event_id))"
        )
        return conn

    def bereits_verarbeitet(self, queue: str, event_id: str) -> bool:
        with closing(self._verbinden()) as conn:
            zeile = conn.execute(
                "SELECT 1 FROM verarbeitete_events WHERE queue = ? AND event_id = ?",
                (queue, event_id),
            ).fetchone()
        return zeile is not None

    def merken(self, queue: str, event_id: str) -> None:
        zeit = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with closing(self._verbinden()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO verarbeitete_events VALUES (?, ?, ?)",
                (queue, event_id, zeit),
            )


def verarbeiten(
    queue: str,
    body: bytes,
    handler: Callable[[Event], None],
    store: VerarbeiteteEvents,
) -> bool:
    """Verarbeitet eine Nachricht hoechstens einmal je `event_id`.

    Gibt True zurueck, wenn der Handler lief, und False, wenn die Nachricht ein
    bereits verarbeitetes Event war. Wirft der Handler, wird nichts gemerkt, die
    Nachricht kann also erneut verarbeitet werden. Stuerzt der Prozess zwischen
    Handler und `merken` ab, kann ein Event ein zweites Mal ankommen (Prototyp).
    """
    event = Event.model_validate_json(body)
    if store.bereits_verarbeitet(queue, event.event_id):
        logger.info(
            "Event {} auf '{}' schon verarbeitet, uebersprungen", event.event_id, queue
        )
        return False
    handler(event)
    store.merken(queue, event.event_id)
    return True


def consume(
    queue: str,
    handler: Callable[[Event], None],
    store: VerarbeiteteEvents | None = None,
) -> None:
    """Verarbeitet Nachrichten einer Queue mit manuellem Ack, jedes Event einmal.

    Nicht verarbeitbare Nachrichten (ungueltiges JSON, Fehler im Handler) werden
    ohne Requeue abgelehnt und landen in der Dead-Letter-Queue. Doppelt
    zugestellte Events (gleiche `event_id`) werden nur bestaetigt.
    """
    store = store or VerarbeiteteEvents()
    with connect(CONSUME_VERSUCHE, CONSUME_PAUSE_SEKUNDEN) as connection:
        channel = connection.channel()
        declare_topology(channel)
        channel.basic_qos(prefetch_count=1)

        def on_message(ch, method, _properties, body):
            try:
                verarbeiten(queue, body, handler, store)
            except Exception:  # noqa: BLE001 - jeder Fehler fuehrt zur Dead-Letter-Queue
                logger.exception("Nachricht nicht verarbeitbar -> Dead-Letter-Queue")
                ch.basic_nack(method.delivery_tag, requeue=False)
            else:
                ch.basic_ack(method.delivery_tag)

        channel.basic_consume(queue, on_message)
        logger.info("Consumer wartet auf Queue '{}'", queue)
        channel.start_consuming()
