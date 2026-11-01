"""Retourenakte: SQLite-Schema und Zugriffsfunktionen (Issue #2).

Die Retourenakte ist die gemeinsame Datenbasis aller Services (adressiert S1:
keine gemeinsame Datenbasis). Der Retouren-Service legt Vorgaenge an, der
gRPC-Wareneingang liest sie (NOT_FOUND, "Retoure bereits storniert?") und setzt
Status. Die Retouren-ID wird hier vergeben (Issue #3), der Zaehler liegt in der
Datenbank, damit IDs auch nach einem Neustart eindeutig bleiben.

Alle Funktionen nehmen optional `db_path` (Standard: `config.DB_PATH`), damit
Tests eine eigene Datenbank verwenden koennen.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

from shopeasy.shared import config
from shopeasy.shared.models import (
    Artikel,
    Kanal,
    NeueRetoure,
    Retoure,
    RetourenStatus,
    StatusEintrag,
    format_retouren_id,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS retouren (
    retouren_id     TEXT PRIMARY KEY,
    kanal           TEXT NOT NULL,
    externe_id      TEXT,
    bestell_nr      TEXT NOT NULL,
    kunde_email     TEXT NOT NULL,
    grund_text      TEXT NOT NULL,
    gemeldet_am     TEXT,
    geliefert_am    TEXT,
    status          TEXT NOT NULL,
    angelegt_am     TEXT NOT NULL,
    aktualisiert_am TEXT NOT NULL,
    UNIQUE (kanal, externe_id)
);

CREATE TABLE IF NOT EXISTS retouren_artikel (
    retouren_id TEXT NOT NULL REFERENCES retouren (retouren_id),
    position    INTEGER NOT NULL,
    sku         TEXT NOT NULL,
    menge       INTEGER NOT NULL CHECK (menge >= 1),
    PRIMARY KEY (retouren_id, position)
);

CREATE TABLE IF NOT EXISTS status_historie (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    retouren_id TEXT NOT NULL REFERENCES retouren (retouren_id),
    status      TEXT NOT NULL,
    zeitpunkt   TEXT NOT NULL,
    quelle      TEXT NOT NULL,
    bemerkung   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_status_historie_retoure
    ON status_historie (retouren_id);

CREATE TABLE IF NOT EXISTS id_zaehler (
    jahr          INTEGER PRIMARY KEY,
    letzte_nummer INTEGER NOT NULL
);
"""


# Spalten, die nach der ersten Version dazugekommen sind. Bestehende Datenbanken
# werden beim Oeffnen automatisch ergaenzt, niemand muss seine Akte loeschen.
NACHGERUESTETE_SPALTEN: dict[str, str] = {
    "geliefert_am": "TEXT",
}


class RetoureNichtGefunden(LookupError):
    def __init__(self, retouren_id: str) -> None:
        super().__init__(f"Retoure {retouren_id} nicht gefunden")
        self.retouren_id = retouren_id


class DubletteError(Exception):
    """Die Marktplatz-Meldung wurde schon angelegt (REST: 409 Conflict)."""

    def __init__(self, bestehende_id: str) -> None:
        super().__init__(f"Meldung bereits als {bestehende_id} angelegt")
        self.bestehende_id = bestehende_id


def zeitstempel(jetzt: datetime | None = None) -> str:
    """UTC-Zeitstempel im gleichen Format wie die Events."""
    return (jetzt or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def verbinden(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Oeffnet die Retourenakte und legt das Schema an, falls noetig."""
    pfad = Path(db_path or config.DB_PATH)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: Transaktionen steuern wir selbst (siehe _transaktion)
    conn = sqlite3.connect(pfad, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _spalten_nachruesten(conn)
    return conn


def _spalten_nachruesten(conn: sqlite3.Connection) -> None:
    vorhanden = {z["name"] for z in conn.execute("PRAGMA table_info(retouren)")}
    for spalte, typ in NACHGERUESTETE_SPALTEN.items():
        if spalte not in vorhanden:
            conn.execute(f"ALTER TABLE retouren ADD COLUMN {spalte} {typ}")


@contextmanager
def _transaktion(db_path: str | Path | None) -> Iterator[sqlite3.Connection]:
    """Schreibende Transaktion; BEGIN IMMEDIATE sperrt sofort gegen parallele
    Schreiber, damit zwei Services nie dieselbe Retouren-ID vergeben."""
    with closing(verbinden(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def _naechste_retouren_id(conn: sqlite3.Connection, jahr: int) -> str:
    conn.execute(
        """
        INSERT INTO id_zaehler (jahr, letzte_nummer) VALUES (?, 1)
        ON CONFLICT (jahr) DO UPDATE SET letzte_nummer = letzte_nummer + 1
        """,
        (jahr,),
    )
    (nummer,) = conn.execute(
        "SELECT letzte_nummer FROM id_zaehler WHERE jahr = ?", (jahr,)
    ).fetchone()
    return format_retouren_id(jahr, nummer)


def _finde_id_per_externer_id(
    conn: sqlite3.Connection, kanal: Kanal, externe_id: str
) -> str | None:
    zeile = conn.execute(
        "SELECT retouren_id FROM retouren WHERE kanal = ? AND externe_id = ?",
        (kanal.value, externe_id),
    ).fetchone()
    return zeile["retouren_id"] if zeile else None


def _lade(conn: sqlite3.Connection, retouren_id: str) -> Retoure | None:
    zeile = conn.execute(
        "SELECT * FROM retouren WHERE retouren_id = ?", (retouren_id,)
    ).fetchone()
    if zeile is None:
        return None
    artikel = conn.execute(
        "SELECT sku, menge FROM retouren_artikel WHERE retouren_id = ?"
        " ORDER BY position",
        (retouren_id,),
    ).fetchall()
    return Retoure(
        retouren_id=zeile["retouren_id"],
        kanal=Kanal(zeile["kanal"]),
        externe_id=zeile["externe_id"],
        bestell_nr=zeile["bestell_nr"],
        kunde_email=zeile["kunde_email"],
        grund_text=zeile["grund_text"],
        gemeldet_am=(
            date.fromisoformat(zeile["gemeldet_am"]) if zeile["gemeldet_am"] else None
        ),
        geliefert_am=(
            date.fromisoformat(zeile["geliefert_am"]) if zeile["geliefert_am"] else None
        ),
        artikel=[Artikel(sku=a["sku"], menge=a["menge"]) for a in artikel],
        status=RetourenStatus(zeile["status"]),
        angelegt_am=zeile["angelegt_am"],
        aktualisiert_am=zeile["aktualisiert_am"],
    )


def anlegen(
    neu: NeueRetoure,
    quelle: str,
    db_path: str | Path | None = None,
    jetzt: datetime | None = None,
) -> Retoure:
    """Legt einen Retourenvorgang an und vergibt die Retouren-ID.

    Soll-BPMN: "Retourenvorgang anlegen, Retouren-ID vergeben".
    Wirft `DubletteError`, wenn dieselbe Marktplatz-Meldung (Kanal + externe_id)
    schon angelegt ist.
    """
    jetzt = jetzt or datetime.now(UTC)
    ts = zeitstempel(jetzt)
    with _transaktion(db_path) as conn:
        if neu.externe_id is not None:
            bestehend = _finde_id_per_externer_id(conn, neu.kanal, neu.externe_id)
            if bestehend is not None:
                raise DubletteError(bestehend)

        retouren_id = _naechste_retouren_id(conn, jetzt.year)
        conn.execute(
            """
            INSERT INTO retouren (retouren_id, kanal, externe_id, bestell_nr,
                kunde_email, grund_text, gemeldet_am, geliefert_am, status,
                angelegt_am, aktualisiert_am)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retouren_id,
                neu.kanal.value,
                neu.externe_id,
                neu.bestell_nr,
                neu.kunde_email,
                neu.grund_text,
                neu.gemeldet_am.isoformat() if neu.gemeldet_am else None,
                neu.geliefert_am.isoformat() if neu.geliefert_am else None,
                RetourenStatus.REGISTRIERT.value,
                ts,
                ts,
            ),
        )
        conn.executemany(
            "INSERT INTO retouren_artikel (retouren_id, position, sku, menge)"
            " VALUES (?, ?, ?, ?)",
            [
                (retouren_id, pos, a.sku, a.menge)
                for pos, a in enumerate(neu.artikel, start=1)
            ],
        )
        conn.execute(
            "INSERT INTO status_historie (retouren_id, status, zeitpunkt, quelle,"
            " bemerkung) VALUES (?, ?, ?, ?, ?)",
            (
                retouren_id,
                RetourenStatus.REGISTRIERT.value,
                ts,
                quelle,
                f"Eingang ueber {neu.kanal.value}",
            ),
        )
        retoure = _lade(conn, retouren_id)
    assert retoure is not None
    return retoure


def holen(retouren_id: str, db_path: str | Path | None = None) -> Retoure | None:
    """Liefert den Retourenvorgang oder None, wenn es ihn nicht gibt."""
    with closing(verbinden(db_path)) as conn:
        return _lade(conn, retouren_id)


def finde_per_externer_id(
    kanal: Kanal, externe_id: str, db_path: str | Path | None = None
) -> Retoure | None:
    """Sucht eine Retoure ueber die ID der Marktplatz-Meldung."""
    with closing(verbinden(db_path)) as conn:
        retouren_id = _finde_id_per_externer_id(conn, kanal, externe_id)
        return _lade(conn, retouren_id) if retouren_id else None


def status_setzen(
    retouren_id: str,
    status: RetourenStatus,
    quelle: str,
    bemerkung: str = "",
    db_path: str | Path | None = None,
    jetzt: datetime | None = None,
) -> Retoure:
    """Setzt den Status und schreibt einen Eintrag in die Historie.

    Die Akte prueft keine Uebergaenge: welche Statuswechsel erlaubt sind,
    entscheidet spaeter der Workflow (Camunda/DMN), nicht die Datenhaltung.
    """
    ts = zeitstempel(jetzt)
    with _transaktion(db_path) as conn:
        geaendert = conn.execute(
            "UPDATE retouren SET status = ?, aktualisiert_am = ? WHERE retouren_id = ?",
            (status.value, ts, retouren_id),
        ).rowcount
        if geaendert == 0:
            raise RetoureNichtGefunden(retouren_id)
        conn.execute(
            "INSERT INTO status_historie (retouren_id, status, zeitpunkt, quelle,"
            " bemerkung) VALUES (?, ?, ?, ?, ?)",
            (retouren_id, status.value, ts, quelle, bemerkung),
        )
        retoure = _lade(conn, retouren_id)
    assert retoure is not None
    return retoure


def historie(
    retouren_id: str, db_path: str | Path | None = None
) -> list[StatusEintrag]:
    """Statushistorie in zeitlicher Reihenfolge (aeltester Eintrag zuerst)."""
    with closing(verbinden(db_path)) as conn:
        if _lade(conn, retouren_id) is None:
            raise RetoureNichtGefunden(retouren_id)
        zeilen = conn.execute(
            "SELECT status, zeitpunkt, quelle, bemerkung FROM status_historie"
            " WHERE retouren_id = ? ORDER BY id",
            (retouren_id,),
        ).fetchall()
    return [
        StatusEintrag(
            status=RetourenStatus(z["status"]),
            zeitpunkt=z["zeitpunkt"],
            quelle=z["quelle"],
            bemerkung=z["bemerkung"],
        )
        for z in zeilen
    ]
