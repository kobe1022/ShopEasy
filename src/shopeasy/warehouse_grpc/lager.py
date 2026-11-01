"""Lagerdaten des WMS: Wareneingang und Pruefergebnis (Issues #15-#18).

Die Tabellen liegen in derselben SQLite-Datei wie die Retourenakte
(`shopeasy.shared.retourenakte`), damit es eine gemeinsame Datenbasis gibt (S1).
Die Retourenakte selbst bleibt unveraendert: Status und Historie pflegt weiter
sie, hier steht nur, was das Lager erfasst hat.

Alle Funktionen nehmen optional `db_path` (Standard: `config.DB_PATH`), damit
Tests eine eigene Datenbank verwenden koennen.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from shopeasy.shared import retourenakte
from shopeasy.shared.models import Zustand

# Soll-BPMN: Ist die Pruefung 24 h nach dem Wareneingang nicht abgeschlossen,
# wird die Lagerleitung informiert.
PRUEFFRIST = timedelta(hours=24)

SCHEMA = """
CREATE TABLE IF NOT EXISTS wareneingang (
    retouren_id       TEXT PRIMARY KEY REFERENCES retouren (retouren_id),
    scanner_id        TEXT NOT NULL,
    eingang_am        TEXT NOT NULL,
    pruef_frist       TEXT NOT NULL,
    already_cancelled INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pruefung (
    retouren_id TEXT PRIMARY KEY REFERENCES retouren (retouren_id),
    zustand     TEXT NOT NULL,
    pruefer     TEXT NOT NULL,
    notiz       TEXT NOT NULL DEFAULT '',
    foto_refs   TEXT NOT NULL DEFAULT '[]',
    erfasst_am  TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Wareneingang:
    retouren_id: str
    scanner_id: str
    eingang_am: str
    pruef_frist: str
    already_cancelled: bool


@dataclass(frozen=True)
class Pruefung:
    retouren_id: str
    zustand: Zustand
    pruefer: str
    notiz: str
    foto_refs: tuple[str, ...]
    erfasst_am: str


class WareneingangExistiert(Exception):
    """Zu dieser Retoure wurde schon ein Wareneingang erfasst (gRPC: ALREADY_EXISTS)."""

    def __init__(self, bestehender: Wareneingang) -> None:
        super().__init__(
            f"Wareneingang zu {bestehender.retouren_id} schon erfasst"
            f" ({bestehender.eingang_am}, Scanner {bestehender.scanner_id})"
        )
        self.bestehender = bestehender


class PruefungExistiert(Exception):
    """Zu dieser Retoure ist schon ein Pruefergebnis erfasst (gRPC: ALREADY_EXISTS)."""

    def __init__(self, bestehende: Pruefung) -> None:
        super().__init__(
            f"Pruefung zu {bestehende.retouren_id} schon erfasst"
            f" ({bestehende.zustand.value} durch {bestehende.pruefer},"
            f" {bestehende.erfasst_am})"
        )
        self.bestehende = bestehende


def _verbinden(db_path: str | Path | None) -> sqlite3.Connection:
    """Oeffnet die Retourenakte und legt die Lager-Tabellen an, falls noetig."""
    conn = retourenakte.verbinden(db_path)
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def _transaktion(db_path: str | Path | None) -> Iterator[sqlite3.Connection]:
    """Schreibende Transaktion mit sofortiger Sperre, wie in der Retourenakte."""
    with closing(_verbinden(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


# --- Wareneingang -----------------------------------------------------------


def _lade_wareneingang(
    conn: sqlite3.Connection, retouren_id: str
) -> Wareneingang | None:
    zeile = conn.execute(
        "SELECT * FROM wareneingang WHERE retouren_id = ?", (retouren_id,)
    ).fetchone()
    if zeile is None:
        return None
    return Wareneingang(
        retouren_id=zeile["retouren_id"],
        scanner_id=zeile["scanner_id"],
        eingang_am=zeile["eingang_am"],
        pruef_frist=zeile["pruef_frist"],
        already_cancelled=bool(zeile["already_cancelled"]),
    )


def wareneingang_erfassen(
    retouren_id: str,
    scanner_id: str,
    eingang: datetime,
    already_cancelled: bool,
    db_path: str | Path | None = None,
) -> Wareneingang:
    """Speichert den Wareneingang und berechnet die Pruefungsfrist (24 h).

    Soll-BPMN: "Wareneingang registrieren, Pruefrist setzen". Die Retoure muss
    in der Retourenakte existieren (Fremdschluessel). Wirft
    `WareneingangExistiert`, wenn es zu ihr schon einen Wareneingang gibt: ein
    doppelter Scan aendert nichts am ersten Eintrag.
    """
    eintrag = Wareneingang(
        retouren_id=retouren_id,
        scanner_id=scanner_id,
        eingang_am=retourenakte.zeitstempel(eingang),
        pruef_frist=retourenakte.zeitstempel(eingang + PRUEFFRIST),
        already_cancelled=already_cancelled,
    )
    with _transaktion(db_path) as conn:
        bestehender = _lade_wareneingang(conn, retouren_id)
        if bestehender is not None:
            raise WareneingangExistiert(bestehender)
        conn.execute(
            "INSERT INTO wareneingang (retouren_id, scanner_id, eingang_am,"
            " pruef_frist, already_cancelled) VALUES (?, ?, ?, ?, ?)",
            (
                eintrag.retouren_id,
                eintrag.scanner_id,
                eintrag.eingang_am,
                eintrag.pruef_frist,
                int(eintrag.already_cancelled),
            ),
        )
    return eintrag


def wareneingang_holen(
    retouren_id: str, db_path: str | Path | None = None
) -> Wareneingang | None:
    """Liefert den erfassten Wareneingang oder None."""
    with closing(_verbinden(db_path)) as conn:
        return _lade_wareneingang(conn, retouren_id)


# --- Pruefergebnis ----------------------------------------------------------


def _lade_pruefung(conn: sqlite3.Connection, retouren_id: str) -> Pruefung | None:
    zeile = conn.execute(
        "SELECT * FROM pruefung WHERE retouren_id = ?", (retouren_id,)
    ).fetchone()
    if zeile is None:
        return None
    return Pruefung(
        retouren_id=zeile["retouren_id"],
        zustand=Zustand(zeile["zustand"]),
        pruefer=zeile["pruefer"],
        notiz=zeile["notiz"],
        foto_refs=tuple(json.loads(zeile["foto_refs"])),
        erfasst_am=zeile["erfasst_am"],
    )


def pruefung_erfassen(
    retouren_id: str,
    zustand: Zustand,
    pruefer: str,
    notiz: str,
    foto_refs: list[str],
    erfasst: datetime,
    db_path: str | Path | None = None,
) -> Pruefung:
    """Speichert das Pruefergebnis (Soll-BPMN: "Pruefergebnis im WMS speichern").

    Wirft `PruefungExistiert`, wenn es zu der Retoure schon eines gibt: eine
    dokumentierte Entscheidung wird nicht stillschweigend ueberschrieben (S3).
    """
    eintrag = Pruefung(
        retouren_id=retouren_id,
        zustand=zustand,
        pruefer=pruefer,
        notiz=notiz,
        foto_refs=tuple(foto_refs),
        erfasst_am=retourenakte.zeitstempel(erfasst),
    )
    with _transaktion(db_path) as conn:
        bestehende = _lade_pruefung(conn, retouren_id)
        if bestehende is not None:
            raise PruefungExistiert(bestehende)
        conn.execute(
            "INSERT INTO pruefung (retouren_id, zustand, pruefer, notiz, foto_refs,"
            " erfasst_am) VALUES (?, ?, ?, ?, ?, ?)",
            (
                eintrag.retouren_id,
                eintrag.zustand.value,
                eintrag.pruefer,
                eintrag.notiz,
                json.dumps(list(eintrag.foto_refs)),
                eintrag.erfasst_am,
            ),
        )
    return eintrag


def pruefung_holen(
    retouren_id: str, db_path: str | Path | None = None
) -> Pruefung | None:
    """Liefert das erfasste Pruefergebnis oder None."""
    with closing(_verbinden(db_path)) as conn:
        return _lade_pruefung(conn, retouren_id)
