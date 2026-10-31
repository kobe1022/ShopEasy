"""Event-Schema und Routing-Keys (Schnittstelle zwischen allen Services).

Aenderungen hier nur nach Absprache im Team: alle Services haengen daran.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from shopeasy.shared.models import Artikel, Kanal, RetourenStatus, Zustand

SCHEMA_VERSION = 1


class EventType(StrEnum):
    """Routing-Keys, 1:1 aus den Status-Events des Soll-BPMN."""

    RETOURE_REGISTRIERT = "retoure.registriert"
    RETOURE_ABGELEHNT = "retoure.abgelehnt"
    LABEL_BEREITGESTELLT = "label.bereitgestellt"
    RUECKSENDUNG_UNTERWEGS = "ruecksendung.unterwegs"
    WARE_EINGEGANGEN = "ware.eingegangen"
    PRUEFUNG_ABGESCHLOSSEN = "pruefung.abgeschlossen"
    RETOURE_ANGENOMMEN = "retoure.angenommen"
    ERSTATTUNG_ABGESCHLOSSEN = "erstattung.abgeschlossen"
    RETOURE_STORNIERT = "retoure.storniert"


class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    retouren_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    source: str
    schema_version: int = SCHEMA_VERSION
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Payload je Event-Typ (Issue #1)
#
# `Event.payload` bleibt im Nachrichtenformat ein einfaches JSON-Objekt. Welche
# Felder darin stehen, legen die Modelle unten fest. Sender bauen Events ueber
# `build_event` (prueft den Payload), Consumer lesen ihn ueber `parse_payload`.
# ---------------------------------------------------------------------------


class RetoureRegistriertPayload(BaseModel):
    kanal: Kanal
    externe_id: str | None = None
    bestell_nr: str
    kunde_email: str
    grund_text: str
    artikel: list[Artikel]


class RetoureAbgelehntPayload(BaseModel):
    grund: str


class LabelBereitgestelltPayload(BaseModel):
    tracking_nr: str
    versanddienstleister: str


class RuecksendungUnterwegsPayload(BaseModel):
    tracking_nr: str


class WareEingegangenPayload(BaseModel):
    scanner_id: str
    pruef_frist: str  # Zeitstempel, bis wann die Pruefung erfolgen muss (24 h)
    already_cancelled: bool = False  # Gateway "Retoure bereits storniert?"


class PruefungAbgeschlossenPayload(BaseModel):
    condition: Zustand
    inspector: str
    note: str = ""
    photo_refs: list[str] = Field(default_factory=list)


class RetoureAngenommenPayload(BaseModel):
    entschieden_durch: str  # z.B. "dmn" oder Kuerzel der Sachbearbeitung


class ErstattungAbgeschlossenPayload(BaseModel):
    betrag: float = Field(ge=0)
    art: Literal["ZAHLUNG", "GUTSCHEIN"]


class RetoureStorniertPayload(BaseModel):
    grund: str


PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.RETOURE_REGISTRIERT: RetoureRegistriertPayload,
    EventType.RETOURE_ABGELEHNT: RetoureAbgelehntPayload,
    EventType.LABEL_BEREITGESTELLT: LabelBereitgestelltPayload,
    EventType.RUECKSENDUNG_UNTERWEGS: RuecksendungUnterwegsPayload,
    EventType.WARE_EINGEGANGEN: WareEingegangenPayload,
    EventType.PRUEFUNG_ABGESCHLOSSEN: PruefungAbgeschlossenPayload,
    EventType.RETOURE_ANGENOMMEN: RetoureAngenommenPayload,
    EventType.ERSTATTUNG_ABGESCHLOSSEN: ErstattungAbgeschlossenPayload,
    EventType.RETOURE_STORNIERT: RetoureStorniertPayload,
}

# Welcher Status in der Retourenakte gehoert zu welchem Event?
EVENT_ZU_STATUS: dict[EventType, RetourenStatus] = {
    EventType.RETOURE_REGISTRIERT: RetourenStatus.REGISTRIERT,
    EventType.RETOURE_ABGELEHNT: RetourenStatus.ABGELEHNT,
    EventType.LABEL_BEREITGESTELLT: RetourenStatus.LABEL_BEREITGESTELLT,
    EventType.RUECKSENDUNG_UNTERWEGS: RetourenStatus.RUECKSENDUNG_UNTERWEGS,
    EventType.WARE_EINGEGANGEN: RetourenStatus.WARE_EINGEGANGEN,
    EventType.PRUEFUNG_ABGESCHLOSSEN: RetourenStatus.PRUEFUNG_ABGESCHLOSSEN,
    EventType.RETOURE_ANGENOMMEN: RetourenStatus.ANGENOMMEN,
    EventType.ERSTATTUNG_ABGESCHLOSSEN: RetourenStatus.ERSTATTUNG_ABGESCHLOSSEN,
    EventType.RETOURE_STORNIERT: RetourenStatus.STORNIERT,
}


def build_event(
    event_type: EventType, retouren_id: str, source: str, payload: BaseModel
) -> Event:
    """Baut ein Event und prueft, dass der Payload zum Event-Typ passt."""
    erwartet = PAYLOAD_MODELS[event_type]
    if not isinstance(payload, erwartet):
        raise TypeError(
            f"{event_type.value} erwartet {erwartet.__name__},"
            f" nicht {type(payload).__name__}"
        )
    return Event(
        event_type=event_type,
        retouren_id=retouren_id,
        source=source,
        payload=payload.model_dump(mode="json"),
    )


def parse_payload(event: Event) -> BaseModel:
    """Liest den Payload eines empfangenen Events als passendes Modell."""
    return PAYLOAD_MODELS[event.event_type].model_validate(event.payload)
