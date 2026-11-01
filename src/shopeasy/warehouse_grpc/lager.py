"""Lagerdaten des WMS: Wareneingang und Pruefergebnis (Issues #15-#18).

Die Tabellen liegen in derselben SQLite-Datei wie die Retourenakte
(`shopeasy.shared.retourenakte`), damit es eine gemeinsame Datenbasis gibt (S1).
Die Retourenakte selbst bleibt unveraendert: Status und Historie pflegt weiter
sie, hier steht nur, was das Lager erfasst hat.

Alle Funktionen nehmen optional `db_path` (Standard: `config.DB_PATH`), damit
Tests eine eigene Datenbank verwenden koennen.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from shopeasy.shared import retourenakte

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
"""


@dataclass(frozen=True)
class Wareneingang:
    retouren_id: str
    scanner_id: str
    eingang_am: str
    pruef_frist: str
    already_cancelled: bool


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


def wareneingang_erfassen(
    retouren_id: str,
    scanner_id: str,
    eingang: datetime,
    already_cancelled: bool,
    db_path: str | Path | None = None,
) -> Wareneingang:
    """Speichert den Wareneingang und berechnet die Pruefungsfrist (24 h).

    Soll-BPMN: "Wareneingang registrieren, Pruefrist setzen". Die Retoure muss
    in der Retourenakte existieren (Fremdschluessel).
    """
    eintrag = Wareneingang(
        retouren_id=retouren_id,
        scanner_id=scanner_id,
        eingang_am=retourenakte.zeitstempel(eingang),
        pruef_frist=retourenakte.zeitstempel(eingang + PRUEFFRIST),
        already_cancelled=already_cancelled,
    )
    with _transaktion(db_path) as conn:
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
