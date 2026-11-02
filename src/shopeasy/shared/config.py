"""Zentrale Konfiguration, ueberschreibbar per Umgebungsvariablen.

Adressen stehen als 127.0.0.1 statt localhost: Unter Windows probiert `localhost`
zuerst IPv6, und jeder HTTP-Aufruf wartet dann gut 2 Sekunden, bis er auf IPv4
wechselt. Die Dienste lauschen nur auf IPv4 (uvicorn: 127.0.0.1).
"""

import os

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/")
DB_PATH = os.environ.get("DB_PATH", "data/retourenakte.db")
EVENTLOG_PATH = os.environ.get("EVENTLOG_PATH", "data/eventlog.csv")
IDEMPOTENZ_DB = os.environ.get("IDEMPOTENZ_DB", "data/verarbeitete_events.db")

MARKETPLACE_MOCK_PORT = int(os.environ.get("MARKETPLACE_MOCK_PORT", "8001"))
RETURN_SERVICE_PORT = int(os.environ.get("RETURN_SERVICE_PORT", "8002"))
MARKETPLACE_MOCK_URL = os.environ.get(
    "MARKETPLACE_MOCK_URL", f"http://127.0.0.1:{MARKETPLACE_MOCK_PORT}"
)
WAREHOUSE_GRPC_ADDRESS = os.environ.get("WAREHOUSE_GRPC_ADDRESS", "127.0.0.1:50051")
