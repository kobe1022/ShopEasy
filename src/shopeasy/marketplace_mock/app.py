"""Mock-Marktplatz (simuliert Amazon und Zalando). Zustaendig: Nikky.

Amazon und Zalando liefern Retourenmeldungen in unterschiedlichen JSON-Formaten
(siehe `formate.py`). Der Retouren-Service von ShopEasy holt neue Meldungen hier
ab (Polling) und quittiert sie, siehe docs/sprint2-plan.md, Abschnitt 3.
"""

from typing import Literal

from fastapi import FastAPI, HTTPException

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn
from shopeasy.marketplace_mock.testdaten import amazon_testdaten, zalando_testdaten

app = FastAPI(title="ShopEasy Mock-Marktplatz", version="0.1.0")

Marketplace = Literal["amazon", "zalando"]
Meldung = AmazonReturn | ZalandoReturn

# Status in der URL einheitlich, intern spricht jeder Marktplatz seine Sprache
StatusFilter = Literal["new", "acknowledged", "all"]
STATUS_WERTE: dict[str, dict[str, str]] = {
    "amazon": {"new": "NEW", "acknowledged": "ACKNOWLEDGED"},
    "zalando": {"new": "announced", "acknowledged": "confirmed"},
}

# "Datenbank" des Mocks: je Marktplatz die Meldungen, Schluessel = Meldungs-ID.
# Liegt nur im Speicher; nach einem Neustart sind wieder die Testdaten da.
MELDUNGEN: dict[str, dict[str, Meldung]] = {}


def zuruecksetzen() -> None:
    """Laedt die Testdaten (Ausgangszustand fuer Demo und Tests)."""
    MELDUNGEN["amazon"] = {r.returnId: r for r in amazon_testdaten()}
    MELDUNGEN["zalando"] = {r.id: r for r in zalando_testdaten()}


zuruecksetzen()


def _status(meldung: Meldung) -> str:
    return meldung.status if isinstance(meldung, AmazonReturn) else meldung.state


def _not_implemented() -> HTTPException:
    return HTTPException(status_code=501, detail="noch nicht implementiert")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/{marketplace}/returns", response_model=list[Meldung])
def list_returns(marketplace: Marketplace, status: StatusFilter = "new"):
    """Retourenmeldungen abrufen, z.B. /amazon/returns?status=new."""
    meldungen = list(MELDUNGEN[marketplace].values())
    if status == "all":
        return meldungen
    gesucht = STATUS_WERTE[marketplace][status]
    return [m for m in meldungen if _status(m) == gesucht]


def _meldung_oder_404(marketplace: str, return_id: str) -> Meldung:
    meldung = MELDUNGEN[marketplace].get(return_id)
    if meldung is None:
        raise HTTPException(
            status_code=404,
            detail=f"Meldung {return_id} bei {marketplace} nicht gefunden",
        )
    return meldung


@app.get("/{marketplace}/returns/{return_id}", response_model=Meldung)
def get_return(marketplace: Marketplace, return_id: str):
    """Einzelne Retourenmeldung abrufen (404, wenn es sie nicht gibt)."""
    return _meldung_oder_404(marketplace, return_id)


@app.post("/{marketplace}/returns/{return_id}/ack")
def acknowledge_return(marketplace: Marketplace, return_id: str):
    """Meldung als uebernommen quittieren."""
    raise _not_implemented()


@app.post("/{marketplace}/returns", status_code=201)
def create_test_return(marketplace: Marketplace):
    """Testfall fuer die Demo erzeugen."""
    raise _not_implemented()
