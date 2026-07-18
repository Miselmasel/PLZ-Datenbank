# -*- coding: utf-8 -*-
"""
Automatisierte Tests für update_plz_datenbank.py.

Alle Pfade (Datenbank, Backups, Log) werden pro Test auf ein temporäres
Verzeichnis umgebogen, damit die Tests weder das echte Repository
verändern noch sich gegenseitig beeinflussen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import update_plz_datenbank as updater  # noqa: E402

SAMPLE_CSV_4_ORTE = """osm_id,ort,plz,bundesland
1,Radeberg,01454,Sachsen
2,Wachau,01454,Sachsen
3,Aach,78267,Baden-Württemberg
5,Westoverledingen,26810,Niedersachsen
"""

SAMPLE_CSV_5_ORTE = SAMPLE_CSV_4_ORTE + "6,Moormerland,26802,Niedersachsen\n"

SAMPLE_CSV_1_ORT = """osm_id,ort,plz,bundesland
1,Radeberg,01454,Sachsen
"""


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Biegt alle Modul-Pfade auf ein Temp-Verzeichnis um."""
    db_path = tmp_path / "plz_datenbank.sqlite3"
    tmp_db_path = tmp_path / "plz_datenbank.sqlite3.tmp"
    backup_dir = tmp_path / "backups"
    log_path = tmp_path / "update_log.jsonl"

    monkeypatch.setattr(updater, "DB_PATH", db_path)
    monkeypatch.setattr(updater, "TMP_DB_PATH", tmp_db_path)
    monkeypatch.setattr(updater, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(updater, "LOG_PATH", log_path)

    return {"db": db_path, "tmp_db": tmp_db_path, "backups": backup_dir, "log": log_path}


def _write_csv(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _run_main(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["update_plz_datenbank.py", *argv])
    return updater.main()


def _last_log_entry(log_path: Path) -> dict:
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1])


def test_first_run_creates_database(isolated_paths, tmp_path, monkeypatch):
    csv_path = _write_csv(tmp_path, "v1.csv", SAMPLE_CSV_4_ORTE)

    exit_code = _run_main(monkeypatch, ["--csv", csv_path])

    assert exit_code == 0
    assert isolated_paths["db"].exists()
    entry = _last_log_entry(isolated_paths["log"])
    assert entry["status"] == "aktualisiert"
    assert entry["neue_kennzahlen"]["orte"] == 4


def test_second_run_with_identical_data_is_noop(isolated_paths, tmp_path, monkeypatch):
    csv_path = _write_csv(tmp_path, "v1.csv", SAMPLE_CSV_4_ORTE)
    assert _run_main(monkeypatch, ["--csv", csv_path]) == 0

    exit_code = _run_main(monkeypatch, ["--csv", csv_path])

    assert exit_code == 0
    entry = _last_log_entry(isolated_paths["log"])
    assert entry["status"] == "unveraendert"
    # Bei "unveraendert" darf kein Backup angelegt worden sein
    assert not isolated_paths["backups"].exists() or not list(isolated_paths["backups"].glob("*.sqlite3"))


def test_run_with_more_data_creates_backup_and_updates(isolated_paths, tmp_path, monkeypatch):
    csv_v1 = _write_csv(tmp_path, "v1.csv", SAMPLE_CSV_4_ORTE)
    csv_v2 = _write_csv(tmp_path, "v2.csv", SAMPLE_CSV_5_ORTE)
    assert _run_main(monkeypatch, ["--csv", csv_v1]) == 0

    exit_code = _run_main(monkeypatch, ["--csv", csv_v2])

    assert exit_code == 0
    entry = _last_log_entry(isolated_paths["log"])
    assert entry["status"] == "aktualisiert"
    assert entry["neue_kennzahlen"]["orte"] == 5
    backups = list(isolated_paths["backups"].glob("plz_datenbank_*.sqlite3"))
    assert len(backups) == 1


def test_drastic_shrink_is_aborted_without_force(isolated_paths, tmp_path, monkeypatch):
    csv_v1 = _write_csv(tmp_path, "v1.csv", SAMPLE_CSV_4_ORTE)
    csv_small = _write_csv(tmp_path, "small.csv", SAMPLE_CSV_1_ORT)
    assert _run_main(monkeypatch, ["--csv", csv_v1]) == 0

    exit_code = _run_main(monkeypatch, ["--csv", csv_small])

    assert exit_code == 1
    entry = _last_log_entry(isolated_paths["log"])
    assert entry["status"] == "abgebrochen"
    # Die produktive Datenbank darf durch den Abbruch nicht verändert worden sein
    assert updater.get_counts(isolated_paths["db"])["orte"] == 4


def test_drastic_shrink_succeeds_with_force(isolated_paths, tmp_path, monkeypatch):
    csv_v1 = _write_csv(tmp_path, "v1.csv", SAMPLE_CSV_4_ORTE)
    csv_small = _write_csv(tmp_path, "small.csv", SAMPLE_CSV_1_ORT)
    assert _run_main(monkeypatch, ["--csv", csv_v1]) == 0

    exit_code = _run_main(monkeypatch, ["--csv", csv_small, "--force"])

    assert exit_code == 0
    entry = _last_log_entry(isolated_paths["log"])
    assert entry["status"] == "aktualisiert"
    assert updater.get_counts(isolated_paths["db"])["orte"] == 1


def test_backup_rotation_keeps_only_max_backups(isolated_paths, tmp_path, monkeypatch):
    base_rows = "osm_id,ort,plz,bundesland\n1,Radeberg,01454,Sachsen\n"
    csv_path = _write_csv(tmp_path, "v0.csv", base_rows)
    assert _run_main(monkeypatch, ["--csv", csv_path]) == 0

    # Mehr Läufe als MAX_BACKUPS, jeweils mit einer zusätzlichen Zeile,
    # damit jeder Lauf tatsächlich ein Update (und damit ein Backup) auslöst.
    for i in range(updater.MAX_BACKUPS + 2):
        base_rows += f"{i+2},Ort{i},{10000+i:05d},Sachsen\n"
        csv_path = _write_csv(tmp_path, f"v{i+1}.csv", base_rows)
        assert _run_main(monkeypatch, ["--csv", csv_path, "--force"]) == 0

    backups = list(isolated_paths["backups"].glob("plz_datenbank_*.sqlite3"))
    assert len(backups) <= updater.MAX_BACKUPS


def test_get_counts_returns_zero_for_missing_database(tmp_path):
    missing_path = tmp_path / "does_not_exist.sqlite3"
    assert updater.get_counts(missing_path) == {"plz": 0, "orte": 0, "bundeslaender": 0}
