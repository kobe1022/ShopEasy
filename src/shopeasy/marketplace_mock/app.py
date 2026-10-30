"""Mock-Marktplatz (simuliert Amazon und Zalando). Zustaendig: Nikky.

TODO: Amazon und Zalando bekommen bewusst unterschiedliche JSON-Formate
(Feldnamen, Datumsformate, Grund-Codes), siehe docs/sprint2-plan.md, Abschnitt 3.
"""

from typing import Literal

from fastapi import FastAPI, HTTPException

app = FastAPI(title="ShopEasy Mock-Marktplatz", version="0.1.0")

Marketplace = Literal["amazon", "zalando"]


def _not_implemented() -> HTTPException:
    return HTTPException(status_code=501, detail="noch nicht implementiert")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/{marketplace}/returns")
def list_returns(marketplace: Marketplace, status: str = "new"):
    """Retourenmeldungen abrufen, z.B. /amazon/returns?status=new."""
    raise _not_implemented()


@app.get("/{marketplace}/returns/{return_id}")
def get_return(marketplace: Marketplace, return_id: str):
    raise _not_implemented()


@app.post("/{marketplace}/returns/{return_id}/ack")
def acknowledge_return(marketplace: Marketplace, return_id: str):
    """Meldung als uebernommen quittieren."""
    raise _not_implemented()


@app.post("/{marketplace}/returns", status_code=201)
def create_test_return(marketplace: Marketplace):
    """Testfall fuer die Demo erzeugen."""
    raise _not_implemented()
