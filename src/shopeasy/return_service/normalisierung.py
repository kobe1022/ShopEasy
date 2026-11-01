"""Normalisierung: Marktplatz-Formate -> einheitliches Modell (Issue #9).

Jeder Marktplatz meldet Retouren in seinem eigenen Format (siehe
`shopeasy.marketplace_mock.formate`, das ist der veroeffentlichte Vertrag der
Marktplatz-APIs). Hier werden sie in `NeueRetoure` uebersetzt, damit alle
weiteren Schritte nur noch ein Format kennen. Das behebt den Medienbruch aus S1.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import ValidationError

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn
from shopeasy.return_service.artikelstamm import UnbekannteEAN, sku_fuer_ean
from shopeasy.shared.models import Artikel, Kanal, NeueRetoure


class MeldungNichtUebersetzbar(Exception):
    """Die Meldung hat einen Inhalt, den das einheitliche Modell nicht annimmt.

    Beispiele: ungueltige E-Mail-Adresse, unmoegliches Datum, unbekannte EAN.
    Soll-BPMN: Solche Meldungen gehen in "Anmeldung pruefen und vervollstaendigen"
    (manuelle Nacharbeit), sie duerfen weder den Service noch das Polling stoppen.
    """


# Amazon-Grundcodes in Klartext fuer Sachbearbeitung und KI-Agent (Sprint 5)
AMAZON_GRUENDE: dict[str, str] = {
    "APPAREL_TOO_SMALL": "Zu klein",
    "APPAREL_TOO_LARGE": "Zu gross",
    "DEFECTIVE": "Defekt",
    "NOT_AS_DESCRIBED": "Entspricht nicht der Beschreibung",
    "UNWANTED_ITEM": "Gefaellt nicht / nicht mehr gewuenscht",
    "OTHER": "Sonstiges",
}


def _grund_mit_kommentar(grund: str, kommentar: str) -> str:
    """Grund und Freitext der Kund:in zu einem Text zusammenfuehren."""
    kommentar = kommentar.strip()
    return f"{grund}: {kommentar}" if kommentar else grund


def amazon_zu_neue_retoure(meldung: AmazonReturn) -> NeueRetoure:
    """Uebersetzt eine Amazon-Meldung in das einheitliche Modell."""
    return NeueRetoure(
        kanal=Kanal.AMAZON,
        externe_id=meldung.returnId,
        bestell_nr=meldung.orderId,
        kunde_email=meldung.buyerEmail,
        grund_text=_grund_mit_kommentar(
            AMAZON_GRUENDE[meldung.returnReasonCode], meldung.customerComment
        ),
        artikel=[Artikel(sku=item.sku, menge=item.quantity) for item in meldung.items],
        gemeldet_am=meldung.requestedAt.date(),
        geliefert_am=meldung.deliveryDate,
    )


# Zalando-Grundcodes in Klartext; 99 = "sonstiges", dann zaehlt nur der Freitext
ZALANDO_GRUENDE: dict[int, str] = {
    10: "Zu klein",
    11: "Zu gross",
    20: "Defekt",
    30: "Gefaellt nicht",
    40: "Falscher Artikel",
    99: "Sonstiges",
}


def _datum_tt_mm_jjjj(text: str) -> date:
    """'28.10.2026' -> date(2026, 10, 28)."""
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError as fehler:
        raise ValueError(
            f"Datum '{text}' existiert nicht (Format TT.MM.JJJJ)"
        ) from fehler


def zalando_zu_neue_retoure(meldung: ZalandoReturn) -> NeueRetoure:
    """Uebersetzt eine Zalando-Meldung in das einheitliche Modell.

    Wirft `UnbekannteEAN`, wenn ein Artikel nicht im Artikelstamm steht; die
    Meldung muss dann manuell geprueft werden.
    """
    if meldung.reason.code == 99 and meldung.reason.text.strip():
        # unklarer Freitext: unveraendert weitergeben (KI-Agent, Sprint 5)
        grund_text = meldung.reason.text.strip()
    else:
        grund_text = _grund_mit_kommentar(
            ZALANDO_GRUENDE[meldung.reason.code], meldung.reason.text
        )
    return NeueRetoure(
        kanal=Kanal.ZALANDO,
        externe_id=meldung.id,
        bestell_nr=meldung.order.number,
        kunde_email=meldung.customer.email,
        grund_text=grund_text,
        artikel=[
            Artikel(sku=sku_fuer_ean(a.ean), menge=a.qty) for a in meldung.articles
        ],
        gemeldet_am=_datum_tt_mm_jjjj(meldung.announced_on),
        geliefert_am=_datum_tt_mm_jjjj(meldung.order.delivered_on),
    )


def _fehlertext(fehler: Exception) -> str:
    """Lesbarer Text fuer Sachbearbeitung statt der rohen Pydantic-Ausgabe."""
    if isinstance(fehler, ValidationError):
        return "; ".join(
            f"{'.'.join(str(teil) for teil in e['loc'])}: {e['msg']}"
            for e in fehler.errors()
        )
    return str(fehler)


def uebersetzen(
    marketplace: Literal["amazon", "zalando"], meldung: AmazonReturn | ZalandoReturn
) -> NeueRetoure:
    """Uebersetzt eine Meldung und meldet jeden inhaltlichen Fehler einheitlich.

    Wirft `MeldungNichtUebersetzbar` (nie `ValueError`, `ValidationError` oder
    `UnbekannteEAN`), damit Webhook und Polling nur einen Fehlerfall kennen.
    """
    try:
        if marketplace == "amazon" and isinstance(meldung, AmazonReturn):
            return amazon_zu_neue_retoure(meldung)
        if marketplace == "zalando" and isinstance(meldung, ZalandoReturn):
            return zalando_zu_neue_retoure(meldung)
    except (UnbekannteEAN, ValueError) as fehler:
        # ValidationError ist ein ValueError
        raise MeldungNichtUebersetzbar(_fehlertext(fehler)) from fehler
    raise MeldungNichtUebersetzbar(f"Meldung ist nicht im {marketplace}-Format")
