#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_plz_datenbank.py
========================

Aktualisiert `plz_datenbank.sqlite3` sicher und wiederholbar - gedacht für
regelmäßige automatische Ausführung (Cron, Task Scheduler, GitHub Actions).

Ablauf:
  1. Lädt aktuelle PLZ/Ort/Bundesland-Daten. Gleiche Quellen-Logik wie
     import_plz_data.py: zuerst Direkt-Download von suche-postleitzahl.org,
     sonst automatischer Fallback auf GeoNames - oder eine lokale Datei via
     --csv (z.B. eine manuell aktualisierte Zuordnungsdatei).
  2. Baut daraus eine NEUE Datenbank in einer temporären Datei (die aktuell
     produktive Datenbank bleibt währenddessen unberührt).
  3. Sicherheitscheck: Fällt die neue Datenbank drastisch kleiner aus als die
     bisherige (Standard: < 90 % der Orte-Zeilen), wird der Austausch
     abgebrochen - schützt vor einer defekten/unvollständigen Quelle.
  4. Legt vor dem Austausch ein rotierendes Backup der alten Datenbank an
     (Standard: die letzten 5 Läufe) und ersetzt die Datenbank danach atomar.
  5. Schreibt jeden Lauf als eine Zeile in update_log.jsonl (Zeitstempel,
     Quelle, Kennzahlen vorher/nachher, Status) - so lässt sich der Verlauf
     jederzeit nachvollziehen, auch ohne die Datenbank selbst zu öffnen.

Verwendung:
    python update_plz_datenbank.py                  # automatische Quellenwahl
    python update_plz_datenbank.py --csv datei.csv   # lokale CSV/ZIP erzwingen
    python update_plz_datenbank.py --force           # Sicherheitscheck überspringen
    python update_plz_datenbank.py --min-keep-ratio 0.8

Exit-Code: 0 = erfolgreich aktualisiert oder unverändert, 1 = Fehler/Abbruch.
Das eignet sich direkt für Cron/Task Scheduler/CI, um Fehlschläge zu erkennen.

Regelmäßige Ausführung einrichten:
  - Linux/macOS (cron), Beispiel "jeden Montag 06:00 Uhr":
        0 6 * * 1 cd /pfad/zum/repo && /usr/bin/python3 update_plz_datenbank.py >> logs/cron.log 2>&1
  - Windows (Aufgabenplanung): Aktion "python.exe", Argument
        "C:\\pfad\\zum\\repo\\update_plz_datenbank.py", Trigger z.B. wöchentlich.
  - GitHub Actions: siehe .github/workflows/update-database.yml - läuft
    automatisch nach Zeitplan und committet die aktualisierte Datenbank.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Optional

import import_plz_data as core

REPO_ROOT = Path(__file__).parent
DB_PATH = REPO_ROOT / "plz_datenbank.sqlite3"
TMP_DB_PATH = REPO_ROOT / "plz_datenbank.sqlite3.tmp"
BACKUP_DIR = REPO_ROOT / "backups"
LOG_PATH = REPO_ROOT / "update_log.jsonl"
MAX_BACKUPS = 5
DEFAULT_MIN_KEEP_RATIO = 0.9  # neue DB darf nicht signifikant kleiner sein als die alte


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def get_counts(db_path: Path) -> dict:
    if not db_path.exists():
        return {"plz": 0, "orte": 0, "bundeslaender": 0}
    conn = sqlite3.connect(db_path)
    try:
        return {
            "plz": conn.execute("SELECT COUNT(*) FROM plz").fetchone()[0],
            "orte": conn.execute("SELECT COUNT(*) FROM ort").fetchone()[0],
            "bundeslaender": conn.execute("SELECT COUNT(*) FROM bundesland").fetchone()[0],
        }
    except sqlite3.OperationalError:
        return {"plz": 0, "orte": 0, "bundeslaender": 0}
    finally:
        conn.close()


def rotate_backups() -> None:
    BACKUP_DIR.mkdir(exist_ok=True)
    backups = sorted(BACKUP_DIR.glob("plz_datenbank_*.sqlite3"))
    while len(backups) >= MAX_BACKUPS:
        backups.pop(0).unlink()


def backup_current_db() -> Optional[Path]:
    if not DB_PATH.exists():
        return None
    rotate_backups()
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = BACKUP_DIR / f"plz_datenbank_{stamp}.sqlite3"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def load_source_text(csv_arg: Optional[str]) -> tuple[str, str, str]:
    """Gibt (inhalt, format, quelle_bezeichnung_fuer_log) zurück."""
    if csv_arg:
        text, fmt = core.load_local_file(csv_arg)
        return text, fmt, f"lokale Datei: {csv_arg}"

    text = core.try_download_suche_plz_csv()
    if text is not None:
        return text, "csv", "suche-postleitzahl.org (Direkt-Download)"

    text = core.extract_de_txt(core.download_geonames_zip())
    return text, "geonames_txt", "GeoNames (Fallback)"


def append_log(entry: dict) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Aktualisiert die PLZ-Datenbank sicher und protokolliert den Lauf.")
    parser.add_argument("--csv", help="Lokale CSV/ZIP-Datei statt automatischem Download verwenden")
    parser.add_argument("--force", action="store_true", help="Sicherheitscheck (Mindest-Orte-Anzahl) überspringen")
    parser.add_argument(
        "--min-keep-ratio", type=float, default=DEFAULT_MIN_KEEP_RATIO,
        help=f"Minimaler Anteil an Orten ggü. der alten Datenbank, Standard {DEFAULT_MIN_KEEP_RATIO}",
    )
    args = parser.parse_args()

    started = dt.datetime.now(dt.timezone.utc)
    log_entry: dict = {"timestamp": started.isoformat(), "status": "gestartet"}

    try:
        text, fmt, quelle = load_source_text(args.csv)
        log_entry["quelle"] = quelle

        rows = core.parse_geonames(text) if fmt == "geonames_txt" else core.parse_suche_plz_csv(text)
        if not rows:
            raise RuntimeError("Quelle enthielt nach der Bereinigung keine gültigen Zeilen.")

        old_counts = get_counts(DB_PATH)

        if TMP_DB_PATH.exists():
            TMP_DB_PATH.unlink()
        core.build_database(rows, db_path=TMP_DB_PATH)
        new_counts = get_counts(TMP_DB_PATH)

        log_entry["alte_kennzahlen"] = old_counts
        log_entry["neue_kennzahlen"] = new_counts

        if not args.force and old_counts["orte"] > 0:
            ratio = new_counts["orte"] / old_counts["orte"]
            if ratio < args.min_keep_ratio:
                TMP_DB_PATH.unlink(missing_ok=True)
                grund = (
                    f"Neue Datenbank hat nur {ratio:.1%} der bisherigen Orte "
                    f"({new_counts['orte']} von {old_counts['orte']}). "
                    "Möglicherweise unvollständige Quelle - Abbruch zum Schutz "
                    "der produktiven Datenbank. Mit --force erzwingbar."
                )
                log_entry.update({"status": "abgebrochen", "grund": grund})
                append_log(log_entry)
                print(f"ABGEBROCHEN: {grund}", file=sys.stderr)
                return 1

        if new_counts == old_counts:
            TMP_DB_PATH.unlink(missing_ok=True)
            log_entry["status"] = "unveraendert"
            append_log(log_entry)
            print("Keine Änderungen gegenüber der bisherigen Datenbank - nichts zu tun.")
            return 0

        backup_path = backup_current_db()
        TMP_DB_PATH.replace(DB_PATH)  # atomarer Austausch

        log_entry.update({
            "status": "aktualisiert",
            "backup": str(backup_path) if backup_path else None,
        })
        append_log(log_entry)
        print(f"Datenbank aktualisiert ({quelle}): {old_counts} -> {new_counts}")
        return 0

    except Exception as exc:  # noqa: BLE001 - Top-Level-Fehlerbehandlung für Cron/CI
        TMP_DB_PATH.unlink(missing_ok=True)
        log_entry.update({"status": "fehler", "fehlermeldung": str(exc)})
        append_log(log_entry)
        print(f"FEHLER beim Aktualisieren: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
