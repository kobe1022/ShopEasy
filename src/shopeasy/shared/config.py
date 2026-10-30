"""Zentrale Konfiguration, ueberschreibbar per Umgebungsvariablen."""

import os

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
DB_PATH = os.environ.get("DB_PATH", "data/retourenakte.db")

MARKETPLACE_MOCK_PORT = int(os.environ.get("MARKETPLACE_MOCK_PORT", "8001"))
RETURN_SERVICE_PORT = int(os.environ.get("RETURN_SERVICE_PORT", "8002"))
MARKETPLACE_MOCK_URL = os.environ.get(
    "MARKETPLACE_MOCK_URL", f"http://localhost:{MARKETPLACE_MOCK_PORT}"
)
WAREHOUSE_GRPC_ADDRESS = os.environ.get("WAREHOUSE_GRPC_ADDRESS", "localhost:50051")
