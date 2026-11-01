"""Retouren-Service (ShopEasy-Seite). Zustaendig: Nikky.

TODO (siehe docs/sprint2-plan.md, Abschnitt 3.2):
- neue Meldungen vom Mock-Marktplatz abholen (Polling mit Quittierung)
- Marktplatz-Formate in ein einheitliches Modell normalisieren
- Retourenvorgang in der Retourenakte (SQLite, shopeasy.shared.config.DB_PATH)
  anlegen und Retouren-ID vergeben (Format RET-2026-000123)
- Dublettenpruefung ueber die externe Marktplatz-ID (409 Conflict)
- Event retoure.registriert publizieren (shopeasy.shared.broker.publish)
"""

from typing import Literal

from fastapi import FastAPI, HTTPException

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn
from shopeasy.return_service.normalisierung import (
    amazon_zu_neue_retoure,
    zalando_zu_neue_retoure,
)
from shopeasy.return_service.schemas import RetoureMitHistorie, WebshopAnmeldung
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


@app.post("/returns/marketplace/{marketplace}", status_code=201, response_model=Retoure)
def receive_marketplace_return(
    marketplace: Literal["amazon", "zalando"], meldung: AmazonReturn | ZalandoReturn
):
    """Marktplatz-Meldung entgegennehmen (Webhook, Push statt Polling).

    Soll-BPMN: Start "Marktplatz-Meldung eingegangen (REST)" ->
    "Retourenvorgang anlegen, Retouren-ID vergeben". Die Meldung wird zuerst in
    das einheitliche Modell uebersetzt (Issue #9).
    """
    if marketplace == "amazon" and isinstance(meldung, AmazonReturn):
        neu = amazon_zu_neue_retoure(meldung)
    elif marketplace == "zalando" and isinstance(meldung, ZalandoReturn):
        neu = zalando_zu_neue_retoure(meldung)
    else:
        raise HTTPException(
            status_code=422, detail=f"Meldung ist nicht im {marketplace}-Format"
        )
    return retourenakte.anlegen(neu, quelle=QUELLE)


@app.post("/returns/poll")
def poll_marketplaces():
    """Neue Meldungen von Amazon und Zalando abholen."""
    raise _not_implemented()


@app.get("/returns/{retouren_id}", response_model=RetoureMitHistorie)
def get_return(retouren_id: str):
    """Status und Historie eines Retourenvorgangs (404, wenn es ihn nicht gibt)."""
    retoure = retourenakte.holen(retouren_id)
    if retoure is None:
        raise HTTPException(
            status_code=404, detail=f"Retoure {retouren_id} nicht gefunden"
        )
    return RetoureMitHistorie(
        **retoure.model_dump(), historie=retourenakte.historie(retouren_id)
    )
