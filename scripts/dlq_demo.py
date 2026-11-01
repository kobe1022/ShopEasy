"""Demo-Fall Dead-Letter-Queue (Issue #22).

Schickt eine kaputte Nachricht an den Exchange `retouren.status`. Der Event-Log-
Consumer kann sie nicht verarbeiten, lehnt sie ab (Nack ohne Requeue) und RabbitMQ
schiebt sie in die Fehler-Warteschlange `retouren.dlq`. Sie geht also nicht verloren.

Aufruf (RabbitMQ und der Event-Log-Consumer muessen laufen):
    uv run python scripts/dlq_demo.py
Danach im RabbitMQ-UI (http://localhost:15672) unter Queues -> retouren.dlq ansehen.
"""

import pika

from shopeasy.shared import broker

# Absichtlich kaputt: Event-Typ stimmt, aber im Payload fehlt "condition".
KAPUTTE_NACHRICHT = (
    b'{"event_type": "pruefung.abgeschlossen", "retouren_id": "RET-2026-999999",'
    b' "source": "dlq-demo", "payload": {"inspector": "demo"}}'
)


def kaputte_nachricht_senden() -> None:
    with broker.connect() as connection:
        channel = connection.channel()
        broker.declare_topology(channel)
        channel.basic_publish(
            exchange=broker.EXCHANGE,
            routing_key="pruefung.abgeschlossen",
            body=KAPUTTE_NACHRICHT,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
        )
    print("Kaputte Nachricht gesendet (pruefung.abgeschlossen ohne 'condition').")


if __name__ == "__main__":
    kaputte_nachricht_senden()
