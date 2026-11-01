"""Normalisierung: Marktplatz-Formate -> einheitliches Modell (Issue #9).

Jeder Marktplatz meldet Retouren in seinem eigenen Format (siehe
`shopeasy.marketplace_mock.formate`, das ist der veroeffentlichte Vertrag der
Marktplatz-APIs). Hier werden sie in `NeueRetoure` uebersetzt, damit alle
weiteren Schritte nur noch ein Format kennen. Das behebt den Medienbruch aus S1.
"""

from shopeasy.marketplace_mock.formate import AmazonReturn
from shopeasy.shared.models import Artikel, Kanal, NeueRetoure

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
