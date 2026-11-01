"""HTTP-Client fuer die Marktplatz-APIs (Issue #13).

Der Retouren-Service ruft hier die REST-API des (Mock-)Marktplatzes auf:
neue Meldungen abholen und uebernommene Meldungen quittieren. Die Adresse kommt
aus `config.MARKETPLACE_MOCK_URL` und kann fuer Tests ueberschrieben werden.
"""

from typing import Literal

import httpx
from pydantic import TypeAdapter

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn
from shopeasy.shared import config

Marketplace = Literal["amazon", "zalando"]
MARKETPLACES: tuple[Marketplace, ...] = ("amazon", "zalando")

TIMEOUT_SEKUNDEN = 5.0

_FORMAT: dict[str, TypeAdapter] = {
    "amazon": TypeAdapter(list[AmazonReturn]),
    "zalando": TypeAdapter(list[ZalandoReturn]),
}


class MarktplatzNichtErreichbar(Exception):
    """Der Marktplatz antwortet nicht oder mit einem Fehler."""


def _client(base_url: str | None) -> httpx.Client:
    return httpx.Client(
        base_url=base_url or config.MARKETPLACE_MOCK_URL, timeout=TIMEOUT_SEKUNDEN
    )


def hole_neue_meldungen(
    marketplace: Marketplace, base_url: str | None = None
) -> list[AmazonReturn] | list[ZalandoReturn]:
    """GET /{marketplace}/returns?status=new und Antwort im Format pruefen."""
    try:
        with _client(base_url) as client:
            antwort = client.get(f"/{marketplace}/returns", params={"status": "new"})
            antwort.raise_for_status()
    except httpx.HTTPError as fehler:
        raise MarktplatzNichtErreichbar(f"{marketplace}: {fehler}") from fehler
    return _FORMAT[marketplace].validate_python(antwort.json())


def quittieren(
    marketplace: Marketplace, meldungs_id: str, base_url: str | None = None
) -> None:
    """POST /{marketplace}/returns/{id}/ack: Meldung als uebernommen markieren."""
    try:
        with _client(base_url) as client:
            antwort = client.post(f"/{marketplace}/returns/{meldungs_id}/ack")
            antwort.raise_for_status()
    except httpx.HTTPError as fehler:
        raise MarktplatzNichtErreichbar(f"{marketplace}: {fehler}") from fehler
