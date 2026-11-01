"""Datenformate der simulierten Marktplaetze (Issue #6).

Amazon und Zalando liefern Retourenmeldungen bewusst in unterschiedlichen
Formaten (Feldnamen, Datumsformat, Grund-Codes, Artikelangaben). Genau das ist
der Medienbruch aus Schwachstelle S1: ShopEasy muss beide Formate in das
einheitliche Modell `shopeasy.shared.models.NeueRetoure` ueberfuehren
(Normalisierung im Retouren-Service, Issue #9).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Amazon: englische Feldnamen in camelCase, ISO-Zeitstempel, Grund als Code
# ---------------------------------------------------------------------------

AmazonReasonCode = Literal[
    "APPAREL_TOO_SMALL",
    "APPAREL_TOO_LARGE",
    "DEFECTIVE",
    "NOT_AS_DESCRIBED",
    "UNWANTED_ITEM",
    "OTHER",
]

AmazonStatus = Literal["NEW", "ACKNOWLEDGED"]


class AmazonItem(BaseModel):
    sku: str = Field(min_length=1, examples=["PULLI-BLAU-M"])
    quantity: int = Field(ge=1, examples=[1])


class AmazonReturn(BaseModel):
    """Retourenmeldung im Amazon-Format."""

    returnId: str = Field(examples=["AMZ-RET-001001"])
    orderId: str = Field(examples=["ORD-100234"])
    buyerEmail: str = Field(examples=["kundin@example.com"])
    returnReasonCode: AmazonReasonCode
    customerComment: str = Field(default="", examples=["Faellt klein aus"])
    deliveryDate: date = Field(examples=["2026-10-20"])
    requestedAt: datetime = Field(examples=["2026-10-28T10:15:00Z"])
    items: list[AmazonItem] = Field(min_length=1)
    status: AmazonStatus = "NEW"


# ---------------------------------------------------------------------------
# Zalando: verschachtelte Struktur, Datum als TT.MM.JJJJ, Grund als Zahlencode
# mit Freitext, Artikel ueber EAN statt SKU
# ---------------------------------------------------------------------------

# Zalando-Grundcodes (Auszug): 10 zu klein, 11 zu gross, 20 defekt,
# 30 gefaellt nicht, 40 falscher Artikel, 99 sonstiges (nur Freitext)
ZalandoReasonCode = Literal[10, 11, 20, 30, 40, 99]

ZalandoState = Literal["announced", "confirmed"]

DATUM_TT_MM_JJJJ = r"^\d{2}\.\d{2}\.\d{4}$"


class ZalandoOrder(BaseModel):
    number: str = Field(examples=["ORD-100234"])
    delivered_on: str = Field(pattern=DATUM_TT_MM_JJJJ, examples=["20.10.2026"])


class ZalandoCustomer(BaseModel):
    email: str = Field(examples=["kundin@example.com"])


class ZalandoReason(BaseModel):
    code: ZalandoReasonCode
    text: str = Field(default="", examples=["Farbe anders als auf dem Foto"])


class ZalandoArticle(BaseModel):
    ean: str = Field(pattern=r"^\d{13}$", examples=["4012345000017"])
    qty: int = Field(ge=1, examples=[1])


class ZalandoReturn(BaseModel):
    """Retourenmeldung im Zalando-Format."""

    id: str = Field(examples=["ZRET-2026-001002"])
    order: ZalandoOrder
    customer: ZalandoCustomer
    reason: ZalandoReason
    announced_on: str = Field(pattern=DATUM_TT_MM_JJJJ, examples=["28.10.2026"])
    articles: list[ZalandoArticle] = Field(min_length=1)
    state: ZalandoState = "announced"
