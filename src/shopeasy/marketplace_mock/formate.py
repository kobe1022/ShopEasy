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
