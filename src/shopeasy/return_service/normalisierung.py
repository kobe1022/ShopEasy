"""Normalisierung: Marktplatz-Formate -> einheitliches Modell (Issue #9).

Jeder Marktplatz meldet Retouren in seinem eigenen Format (siehe
`shopeasy.marketplace_mock.formate`, das ist der veroeffentlichte Vertrag der
Marktplatz-APIs). Hier werden sie in `NeueRetoure` uebersetzt, damit alle
weiteren Schritte nur noch ein Format kennen. Das behebt den Medienbruch aus S1.
"""

from datetime import date, datetime

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn
from shopeasy.return_service.artikelstamm import sku_fuer_ean
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
    return datetime.strptime(text, "%d.%m.%Y").date()


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
