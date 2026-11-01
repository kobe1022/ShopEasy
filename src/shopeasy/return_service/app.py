"""Retouren-Service (ShopEasy-Seite). Zustaendig: Nikky.

Nimmt Retourenanmeldungen aus allen Kanaelen an und legt sie in der
Retourenakte an (siehe docs/sprint2-plan.md, Abschnitt 3.2):

- Webshop:     POST /returns
- Marktplatz:  POST /returns/marketplace/{marketplace} (Webhook, Push)
               POST /returns/poll (Abholen mit Quittierung, Pull)
- Abfrage:     GET /returns/{retouren_id} (Status und Historie)

Marktplatz-Formate werden in das einheitliche Modell uebersetzt
(`normalisierung.py`), doppelte Meldungen erkennt die Retourenakte (409).
"""

from typing import Literal

from fastapi import FastAPI, HTTPException

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn
from shopeasy.return_service import marktplatz_client
from shopeasy.return_service.artikelstamm import UnbekannteEAN
from shopeasy.return_service.marktplatz_client import (
    MARKETPLACES,
    MarktplatzNichtErreichbar,
)
from shopeasy.return_service.normalisierung import (
    amazon_zu_neue_retoure,
    zalando_zu_neue_retoure,
)
from shopeasy.return_service.schemas import (
    PollEintrag,
    PollErgebnis,
    RetoureMitHistorie,
    WebshopAnmeldung,
)
from shopeasy.shared import retourenakte
from shopeasy.shared.models import Retoure
from shopeasy.shared.retourenakte import DubletteError

QUELLE = "retouren-service"

UEBERSETZER = {"amazon": amazon_zu_neue_retoure, "zalando": zalando_zu_neue_retoure}

app = FastAPI(title="ShopEasy Retouren-Service", version="0.1.0")


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

    Antworten: 201 angelegt, 409 doppelte Meldung (mit bestehender Retouren-ID),
    422 falsches Format oder unbekannter Artikel.
    """
    try:
        if marketplace == "amazon" and isinstance(meldung, AmazonReturn):
            neu = amazon_zu_neue_retoure(meldung)
        elif marketplace == "zalando" and isinstance(meldung, ZalandoReturn):
            neu = zalando_zu_neue_retoure(meldung)
        else:
            raise HTTPException(
                status_code=422, detail=f"Meldung ist nicht im {marketplace}-Format"
            )
    except UnbekannteEAN as fehler:
        # Soll-BPMN: "Anmeldung pruefen und vervollstaendigen" (manuell)
        raise HTTPException(status_code=422, detail=str(fehler)) from fehler

    try:
        return retourenakte.anlegen(neu, quelle=QUELLE)
    except DubletteError as fehler:
        # Dieselbe Meldung kam schon einmal: keine zweite Retoure anlegen,
        # sondern die bestehende Retouren-ID zurueckmelden (Issue #11).
        raise HTTPException(
            status_code=409,
            detail={
                "meldung": str(fehler),
                "retouren_id": fehler.bestehende_id,
            },
        ) from fehler


@app.post("/returns/poll", response_model=PollErgebnis)
def poll_marketplaces():
    """Neue Meldungen von Amazon und Zalando abholen (Polling mit Quittierung).

    Je Meldung: uebersetzen, Retoure anlegen, beim Marktplatz quittieren.
    Bereits bekannte Meldungen werden nur quittiert (Dublette). Meldungen, die
    sich nicht uebersetzen lassen, werden nicht quittiert und bleiben offen.
    """
    ergebnis = PollErgebnis()
    for marketplace in MARKETPLACES:
        try:
            meldungen = marktplatz_client.hole_neue_meldungen(marketplace)
        except MarktplatzNichtErreichbar:
            ergebnis.nicht_erreichbar.append(marketplace)
            continue

        for meldung in meldungen:
            externe_id = (
                meldung.returnId if isinstance(meldung, AmazonReturn) else meldung.id
            )
            eintrag = PollEintrag(marketplace=marketplace, externe_id=externe_id)
            try:
                neu = UEBERSETZER[marketplace](meldung)
                retoure = retourenakte.anlegen(neu, quelle=QUELLE)
            except UnbekannteEAN as fehler:
                eintrag.hinweis = str(fehler)
                ergebnis.manuell_pruefen.append(eintrag)
                continue  # nicht quittieren, Meldung bleibt beim Marktplatz offen
            except DubletteError as fehler:
                eintrag.retouren_id = fehler.bestehende_id
                eintrag.hinweis = "bereits angelegt, nur quittiert"
                ergebnis.dubletten.append(eintrag)
            else:
                eintrag.retouren_id = retoure.retouren_id
                ergebnis.angelegt.append(eintrag)

            try:
                marktplatz_client.quittieren(marketplace, externe_id)
            except MarktplatzNichtErreichbar as fehler:
                # Beim naechsten Abholen kommt die Meldung wieder, wird dann als
                # Dublette erkannt und erneut quittiert: es geht nichts verloren.
                eintrag.hinweis = f"Quittierung fehlgeschlagen: {fehler}"
    return ergebnis


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
