"""Tests fuer scripts/demo.py (Issue #27): alles, was ohne laufende Dienste pruefbar ist.

Der Ablauf selbst (REST, gRPC, RabbitMQ) wird mit der Demo gegen die Docker-Dienste
vorgefuehrt; hier steht, was kaputtgehen kann, ohne dass es sofort auffaellt.
"""

import importlib.util
import subprocess
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from shopeasy.return_service.artikelstamm import EAN_ZU_SKU
from shopeasy.return_service.normalisierung import uebersetzen
from shopeasy.shared import config
from shopeasy.shared.events import Event, parse_payload
from shopeasy.shared.models import Kanal

PFAD = Path(__file__).resolve().parents[1] / "scripts" / "demo.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo_skript", PFAD)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


# --- Die Demo-Meldung ---------------------------------------------------------


def test_demo_meldung_ist_im_zalando_format_und_wird_uebersetzt(demo):
    meldung = demo.neue_zalando_meldung("TEST")

    neu = uebersetzen("zalando", meldung)

    assert neu.kanal == Kanal.ZALANDO
    assert neu.externe_id == "ZRET-DEMO-TEST"
    assert [a.sku for a in neu.artikel] == ["PULLI-BLAU-M"]


def test_demo_meldung_nutzt_eine_bekannte_ean(demo):
    ean = demo.neue_zalando_meldung().articles[0].ean

    assert ean in EAN_ZU_SKU


def test_demo_meldung_ist_innerhalb_der_frist_geliefert(demo):
    neu = uebersetzen("zalando", demo.neue_zalando_meldung())

    assert (neu.gemeldet_am - neu.geliefert_am).days == 6
    assert neu.gemeldet_am == date.today()


def test_jeder_lauf_bekommt_eine_eigene_id(demo):
    assert demo.neue_zalando_meldung("A").id != demo.neue_zalando_meldung("B").id


# --- Die kaputte Nachricht -------------------------------------------------------


def test_kaputte_nachricht_ist_wirklich_kaputt(demo):
    event = Event.model_validate_json(demo.KAPUTTE_NACHRICHT)

    with pytest.raises(ValidationError):
        parse_payload(event)  # genau das lehnt der Event-Log-Consumer ab


def test_kaputte_nachricht_traegt_die_marke_zum_wiederfinden(demo):
    assert b"demo-skript" in demo.KAPUTTE_NACHRICHT


# --- Bericht und Beendigungscode ------------------------------------------------


def test_bericht_ohne_fehler_endet_mit_0(demo, capsys):
    bericht = demo.Bericht()
    bericht.pruefe("Schritt eins", True)
    bericht.pruefe("Schritt zwei", True)

    assert bericht.zusammenfassung() == 0
    assert "2 von 2 Pruefungen bestanden" in capsys.readouterr().out


def test_bericht_mit_fehler_endet_mit_1_und_nennt_ihn(demo, capsys):
    bericht = demo.Bericht()
    bericht.pruefe("Schritt eins", True)
    bericht.pruefe("Schritt zwei", False, "Antwort 500")

    assert bericht.zusammenfassung() == 1
    ausgabe = capsys.readouterr().out
    assert "[FEHLER] Schritt zwei" in ausgabe
    assert "Antwort 500" in ausgabe
    assert "FEHLGESCHLAGEN: Schritt zwei" in ausgabe


def test_fehlende_dienste_beenden_die_demo_mit_hinweis(demo, monkeypatch, capsys):
    monkeypatch.setattr(demo, "dienste_pruefen", lambda: ["RabbitMQ", "gRPC"])

    code = demo.main([])

    ausgabe = capsys.readouterr().out
    assert code == 2
    assert "RabbitMQ, gRPC" in ausgabe
    assert "docker compose up -d --build" in ausgabe


# --- Anzeige der Ergebnisse -----------------------------------------------------


def test_eventlog_zeilen_nur_der_gesuchten_retoure(demo, monkeypatch, tmp_path):
    (tmp_path / "eventlog.csv").write_text(
        "case_id;activity;timestamp;event_id;source\n"
        "RET-1;retoure.registriert;t1;e1;retouren-service\n"
        "RET-2;retoure.registriert;t2;e2;retouren-service\n"
        "RET-1;ware.eingegangen;t3;e3;warehouse-grpc\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(demo, "PROJEKT", tmp_path)
    monkeypatch.setattr(config, "EVENTLOG_PATH", "eventlog.csv")

    zeilen = demo.eventlog_zeilen("RET-1")

    assert [z["activity"] for z in zeilen] == [
        "retoure.registriert",
        "ware.eingegangen",
    ]


def test_eventlog_zeilen_ohne_datei(demo, monkeypatch, tmp_path):
    monkeypatch.setattr(demo, "PROJEKT", tmp_path)
    monkeypatch.setattr(config, "EVENTLOG_PATH", "gibt-es-nicht.csv")

    assert demo.eventlog_zeilen("RET-1") == []


def lauf_mit_ausgabe(stdout: str, returncode: int = 0):
    return lambda *args, **kwargs: subprocess.CompletedProcess(
        args, returncode, stdout=stdout
    )


def test_status_mails_nur_der_gesuchten_retoure(demo, monkeypatch):
    log = (
        "kundeninfo-1  | 11:00:00 | INFO | Status-Mail an a@b.de | Betreff: X"
        " | Hallo, deine Retoure RET-1 ist da\n"
        "kundeninfo-1  | 11:00:01 | INFO | Status-Mail an c@d.de | Betreff: Y"
        " | Hallo, deine Retoure RET-2 ist da\n"
        "kundeninfo-1  | 11:00:02 | INFO | Consumer wartet auf Queue 'kundeninfo'\n"
    )
    monkeypatch.setattr(subprocess, "run", lauf_mit_ausgabe(log))

    mails = demo.status_mails("RET-1")

    assert len(mails) == 1
    assert mails[0].startswith("a@b.de")


def test_status_mails_ohne_docker_ist_none(demo, monkeypatch):
    def kein_docker(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", kein_docker)

    assert demo.status_mails("RET-1") is None


def test_status_mails_bei_docker_fehler_ist_none(demo, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lauf_mit_ausgabe("", returncode=1))

    assert demo.status_mails("RET-1") is None
