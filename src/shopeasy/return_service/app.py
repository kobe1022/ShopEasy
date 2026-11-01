"""Retouren-Service (ShopEasy-Seite). Zustaendig: Nikky.

TODO (siehe docs/sprint2-plan.md, Abschnitt 3.2):
- neue Meldungen vom Mock-Marktplatz abholen (Polling mit Quittierung)
- Marktplatz-Formate in ein einheitliches Modell normalisieren
- Retourenvorgang in der Retourenakte (SQLite, shopeasy.shared.config.DB_PATH)
  anlegen und Retouren-ID vergeben (Format RET-2026-000123)
- Dublettenpruefung ueber die externe Marktplatz-ID (409 Conflict)
- Event retoure.registriert publizieren (shopeasy.shared.broker.publish)
"""

from fastapi import FastAPI, HTTPException

from shopeasy.return_service.schemas import WebshopAnmeldung
from shopeasy.shared import retourenakte
from shopeasy.shared.models import Retoure

QUELLE = "retouren-service"

app = FastAPI(title="ShopEasy Retouren-Service", version="0.1.0")


def _not_implemented() -> HTTPException:
    return HTTPException(status_code=501, detail="noch nicht implementiert")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/returns", status_code=201, response_model=Retoure)
def create_return(anmeldung: WebshopAnmeldung):
    """Webshop-Anmeldung entgegennehmen und Retourenvorgang anlegen.

    Soll-BPMN: "Retoure ueber Webshop-Formular anmelden" ->
    "Retourenvorgang anlegen, Retouren-ID vergeben".
    """
    return retourenakte.anlegen(anmeldung.als_neue_retoure(), quelle=QUELLE)


@app.post("/returns/poll")
def poll_marketplaces():
    """Neue Meldungen von Amazon und Zalando abholen."""
    raise _not_implemented()


@app.get("/returns/{retouren_id}")
def get_return(retouren_id: str):
    """Status und Historie eines Retourenvorgangs."""
    raise _not_implemented()
