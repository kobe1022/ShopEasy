"""Event-Schema und Routing-Keys (Schnittstelle zwischen allen Services).

Aenderungen hier nur nach Absprache im Team: alle Services haengen daran.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

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
