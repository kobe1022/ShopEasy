"""Einheitliches Retourenmodell (Issue #3).

Egal ob eine Retoure ueber Amazon, Zalando, den Webshop oder per E-Mail kommt:
intern hat sie immer diese Form. Der Retouren-Service normalisiert die
Marktplatz-Formate auf `NeueRetoure` (Issue #9), die Retourenakte speichert sie
und vergibt die Retouren-ID (siehe `shopeasy.shared.retourenakte`).

Aenderungen hier nur nach Absprache im Team: alle Services haengen daran.
"""

import re
from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator

RETOUREN_ID_PATTERN = r"^RET-\d{4}-\d{6}$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class Kanal(StrEnum):
    """Eingangskanal der Retourenanmeldung (Soll-BPMN: drei Startereignisse)."""

    AMAZON = "AMAZON"
    ZALANDO = "ZALANDO"
    WEBSHOP = "WEBSHOP"
    EMAIL = "EMAIL"  # formlose Anmeldung, Auswertung durch KI-Agent in Sprint 5


MARKTPLATZ_KANAELE = frozenset({Kanal.AMAZON, Kanal.ZALANDO})


class RetourenStatus(StrEnum):
    """Status der Retoure, 1:1 zu den Status-Events (siehe `events.EventType`)."""

    REGISTRIERT = "REGISTRIERT"
    ABGELEHNT = "ABGELEHNT"
    LABEL_BEREITGESTELLT = "LABEL_BEREITGESTELLT"
    RUECKSENDUNG_UNTERWEGS = "RUECKSENDUNG_UNTERWEGS"
    WARE_EINGEGANGEN = "WARE_EINGEGANGEN"
    PRUEFUNG_ABGESCHLOSSEN = "PRUEFUNG_ABGESCHLOSSEN"
    ANGENOMMEN = "ANGENOMMEN"
    ERSTATTUNG_ABGESCHLOSSEN = "ERSTATTUNG_ABGESCHLOSSEN"
    STORNIERT = "STORNIERT"


class Zustand(StrEnum):
    """Pruefergebnis im Lager, gleiche Werte wie `Condition` in der .proto-Datei."""

    NEUWERTIG = "NEUWERTIG"
    GETRAGEN = "GETRAGEN"
    BESCHAEDIGT = "BESCHAEDIGT"
    UNVOLLSTAENDIG = "UNVOLLSTAENDIG"
    FALSCHER_ARTIKEL = "FALSCHER_ARTIKEL"


class Artikel(BaseModel):
    sku: str = Field(min_length=1, examples=["PULLI-BLAU-M"])
    menge: int = Field(default=1, ge=1, examples=[1])


class NeueRetoure(BaseModel):
    """Normalisierte Retourenanmeldung, noch ohne Retouren-ID."""

    kanal: Kanal
    externe_id: str | None = Field(
        default=None,
        min_length=1,
        description="ID der Meldung beim Marktplatz, Grundlage der Dublettenpruefung",
        examples=["AMZ-RET-001001"],
    )
    bestell_nr: str = Field(min_length=1, examples=["ORD-100234"])
    kunde_email: str = Field(pattern=EMAIL_PATTERN, examples=["kundin@example.com"])
    grund_text: str = Field(min_length=1, examples=["Zu gross, passt nicht"])
    artikel: list[Artikel] = Field(min_length=1)
    gemeldet_am: date | None = Field(
        default=None, description="Datum der Anmeldung beim Kanal (fuer Fristpruefung)"
    )

    @model_validator(mode="after")
    def _marktplatz_braucht_externe_id(self) -> Self:
        if self.kanal in MARKTPLATZ_KANAELE and not self.externe_id:
            raise ValueError(f"Fuer Kanal {self.kanal} ist externe_id Pflicht")
        return self


class Retoure(NeueRetoure):
    """Retourenvorgang in der Retourenakte."""

    retouren_id: str = Field(pattern=RETOUREN_ID_PATTERN, examples=["RET-2026-000123"])
    status: RetourenStatus
    angelegt_am: str = Field(examples=["2026-11-02T09:41:12Z"])
    aktualisiert_am: str = Field(examples=["2026-11-02T09:41:12Z"])


class StatusEintrag(BaseModel):
    """Ein Eintrag der Statushistorie."""

    status: RetourenStatus
    zeitpunkt: str
    quelle: str
    bemerkung: str = ""


def format_retouren_id(jahr: int, laufnummer: int) -> str:
    """Formatiert eine Retouren-ID, z.B. (2026, 123) -> 'RET-2026-000123'."""
    if not 1 <= laufnummer <= 999_999:
        raise ValueError(f"Laufnummer ausserhalb 1..999999: {laufnummer}")
    return f"RET-{jahr:04d}-{laufnummer:06d}"


def ist_retouren_id(wert: str) -> bool:
    return re.fullmatch(RETOUREN_ID_PATTERN, wert) is not None
