"""Tests fuer die Scanner-CLI (Issue #20), gegen einen laufenden gRPC-Server."""

import pytest

from shopeasy.clients import scanner_cli
from shopeasy.shared import retourenakte
from shopeasy.shared.models import Artikel, Kanal, NeueRetoure, RetourenStatus


def neue_retoure() -> str:
    return retourenakte.anlegen(
        NeueRetoure(
            kanal=Kanal.WEBSHOP,
            bestell_nr="ORD-100300",
            kunde_email="max@example.org",
            grund_text="Farbe gefaellt nicht",
            artikel=[Artikel(sku="SHIRT-WEISS-L")],
        ),
        quelle="test",
    ).retouren_id


@pytest.fixture
def scanner(lager_server, capsys):
    """Fuehrt die CLI gegen den Test-Server aus: (argumente) -> (code, out, err)."""
    adresse, _ = lager_server

    def ausfuehren(*argumente: str) -> tuple[int, str, str]:
        code = scanner_cli.main(["--server", adresse, *argumente])
        ausgabe = capsys.readouterr()
        return code, ausgabe.out, ausgabe.err

    return ausfuehren


def test_wareneingang_wird_lesbar_ausgegeben(scanner):
    retouren_id = neue_retoure()

    code, out, err = scanner("receive", retouren_id)

    assert code == scanner_cli.EXIT_OK
    assert f"Wareneingang erfasst: {retouren_id}" in out
    assert "Pruefung faellig bis:" in out
    assert "ACHTUNG" not in out
    assert err == ""


def test_stornierte_retoure_wird_deutlich_gewarnt(scanner):
    retouren_id = neue_retoure()
    retourenakte.status_setzen(retouren_id, RetourenStatus.STORNIERT, quelle="test")

    code, out, _ = scanner("receive", retouren_id)

    assert code == scanner_cli.EXIT_OK
    assert "ACHTUNG: Die Retoure ist bereits storniert" in out


def test_zustand_mit_foto_und_abfrage(scanner):
    retouren_id = neue_retoure()
    scanner("receive", retouren_id)

    code, out, err = scanner(
        "inspect",
        retouren_id,
        "BESCHAEDIGT",
        "--inspector",
        "lager-02",
        "--note",
        "Naht offen",
        "--photo",
        "foto-001.jpg",
        "--photo",
        "foto-002.jpg",
    )

    assert code == scanner_cli.EXIT_OK
    assert f"Zustand BESCHAEDIGT fuer {retouren_id}" in out
    assert err == ""  # Foto vorhanden, kein Hinweis

    code, out, _ = scanner("get", retouren_id)
    assert code == scanner_cli.EXIT_OK
    assert f"Zustand BESCHAEDIGT fuer {retouren_id}" in out


def test_zustand_wird_auch_klein_geschrieben_akzeptiert(scanner):
    retouren_id = neue_retoure()
    scanner("receive", retouren_id)

    code, out, _ = scanner("inspect", retouren_id, "neuwertig")

    assert code == scanner_cli.EXIT_OK
    assert "Zustand NEUWERTIG" in out


@pytest.mark.parametrize(
    "zustand", ["BESCHAEDIGT", "UNVOLLSTAENDIG", "FALSCHER_ARTIKEL"]
)
def test_hinweis_auf_fotos_bei_schaeden(scanner, zustand):
    retouren_id = neue_retoure()
    scanner("receive", retouren_id)

    code, _, err = scanner("inspect", retouren_id, zustand)

    assert code == scanner_cli.EXIT_OK  # nur ein Hinweis, keine Pflicht
    assert "Fotos beigefuegt werden" in err


def test_kein_fotohinweis_bei_neuwertiger_ware(scanner):
    retouren_id = neue_retoure()
    scanner("receive", retouren_id)

    _, _, err = scanner("inspect", retouren_id, "NEUWERTIG")

    assert err == ""


@pytest.mark.parametrize(
    ("befehl", "erwartet"),
    [
        (("receive", "RET-2026-999999"), "Nicht gefunden: Retoure RET-2026-999999"),
        (("get", "RET-2026-999999"), "Nicht gefunden: Retoure RET-2026-999999"),
    ],
)
def test_unbekannte_retoure_wird_verstaendlich_gemeldet(scanner, befehl, erwartet):
    code, out, err = scanner(*befehl)

    assert code == scanner_cli.EXIT_ABGELEHNT
    assert out == ""
    assert erwartet in err
    assert "StatusCode" not in err  # keine technische Ausgabe


def test_doppelter_scan_wird_als_bereits_erfasst_gemeldet(scanner):
    retouren_id = neue_retoure()
    scanner("receive", retouren_id)

    code, _, err = scanner("receive", retouren_id)

    assert code == scanner_cli.EXIT_ABGELEHNT
    assert err.startswith("Fehler: Bereits erfasst:")


def test_pruefung_vor_wareneingang_wird_als_nicht_moeglich_gemeldet(scanner):
    code, _, err = scanner("inspect", neue_retoure(), "NEUWERTIG")

    assert code == scanner_cli.EXIT_ABGELEHNT
    assert err.startswith("Fehler: Noch nicht moeglich:")


def test_unbekannter_zustand_lehnt_argparse_ab(scanner, capsys):
    with pytest.raises(SystemExit) as beendet:
        scanner("inspect", "RET-2026-000001", "KAPUTT")

    assert beendet.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_server_nicht_erreichbar_hat_eigenen_beendigungscode(capsys):
    code = scanner_cli.main(
        ["--server", "127.0.0.1:1", "--timeout", "1", "get", "RET-2026-000001"]
    )

    assert code == scanner_cli.EXIT_NICHT_ERREICHBAR
    err = capsys.readouterr().err
    assert "127.0.0.1:1" in err
    assert "nicht erreichbar" in err
