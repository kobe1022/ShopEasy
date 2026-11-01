"""HTTP-Client fuer die Marktplatz-APIs (Issue #13).

Der Retouren-Service ruft hier die REST-API des (Mock-)Marktplatzes auf:
neue Meldungen abholen und uebernommene Meldungen quittieren. Die Adresse kommt
aus `config.MARKETPLACE_MOCK_URL` und kann fuer Tests ueberschrieben werden.
"""

from typing import Literal

import httpx
from loguru import logger
from pydantic import TypeAdapter, ValidationError

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn
from shopeasy.shared import config

Marketplace = Literal["amazon", "zalando"]
MARKETPLACES: tuple[Marketplace, ...] = ("amazon", "zalando")

TIMEOUT_SEKUNDEN = 5.0

_EINZELFORMAT: dict[str, TypeAdapter] = {
    "amazon": TypeAdapter(AmazonReturn),
    "zalando": TypeAdapter(ZalandoReturn),
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
    try:
        rohdaten = antwort.json()
    except ValueError as fehler:
        raise MarktplatzNichtErreichbar(
            f"{marketplace}: Antwort ist kein JSON"
        ) from fehler
    if not isinstance(rohdaten, list):
        raise MarktplatzNichtErreichbar(f"{marketplace}: Antwort ist keine Liste")

    # Jede Meldung einzeln pruefen: eine kaputte darf die anderen nicht blockieren.
    # Sie bleibt beim Marktplatz unquittiert und wird im Log gemeldet.
    meldungen = []
    for roh in rohdaten:
        try:
            meldungen.append(_EINZELFORMAT[marketplace].validate_python(roh))
        except ValidationError as fehler:
            meldungs_id = (
                roh.get("returnId") or roh.get("id") if isinstance(roh, dict) else None
            )
            logger.warning(
                "{}: Meldung {} uebersprungen, ungueltiges Format: {}",
                marketplace,
                meldungs_id or "ohne ID",
                fehler.error_count(),
            )
    return meldungen


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
