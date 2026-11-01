"""Gemeinsame Fixtures: laufender gRPC-Wareneingangs-Service mit eigener Akte."""

from concurrent import futures

import grpc
import pytest

from shopeasy.shared import broker, config
from shopeasy.warehouse.v1 import warehouse_pb2_grpc
from shopeasy.warehouse_grpc.server import WarehouseService


@pytest.fixture
def lager_server(monkeypatch, tmp_path):
    """Echter Server auf freiem Port; gibt (Adresse, gesendete Events) zurueck.

    Jeder Test bekommt eine eigene, leere Retourenakte. Der Message Broker wird
    ersetzt: gesendete Events landen in einer Liste, RabbitMQ muss nicht laufen.
    """
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "retourenakte.db"))
    gesendet = []
    monkeypatch.setattr(broker, "publish", gesendet.append)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    warehouse_pb2_grpc.add_WarehouseServiceServicer_to_server(
        WarehouseService(), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield f"127.0.0.1:{port}", gesendet
    server.stop(None).wait()


@pytest.fixture
def lager(lager_server):
    """Stub zum laufenden Server; gibt (Stub, gesendete Events) zurueck."""
    adresse, gesendet = lager_server
    with grpc.insecure_channel(adresse) as kanal:
        yield warehouse_pb2_grpc.WarehouseServiceStub(kanal), gesendet
