# -*- coding: utf-8 -*-
"""
Automatisierte Tests für import_plz_data.py.

Die Tests arbeiten ausschließlich mit kleinen, lokalen Beispieldaten
(kein Netzwerkzugriff), damit sie deterministisch und in CI stabil laufen.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Repo-Root zum Modulpfad hinzufügen, damit import_plz_data.py gefunden wird,
# egal von wo pytest gestartet wird.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import import_plz_data as plzmod  # noqa: E402


# ---------------------------------------------------------------------------
# Beispieldaten
# ---------------------------------------------------------------------------

SAMPLE_SUCHE_PLZ_CSV = """osm_id,ort,plz,bundesland
1,Radeberg,01454,Sachsen
2,Wachau,01454,Sachsen
3,Aach,78267,Baden-Württemberg
3,Aach,78267,Baden-Württemberg
5,Westoverledingen,26810,Niedersachsen
6,,99999,Niedersachsen
7,  Musterstadt  ,1234,Bayern
"""

SAMPLE_GEONAMES_TXT = (
    "DE\t01454\tRadeberg\tSachsen\t14\tLandkreis Bautzen\t14625\t\t\t51.1\t13.9\t4\n"
    "DE\t01454\tWachau\tSachsen\t14\tLandkreis Bautzen\t14625\t\t\t51.2\t13.8\t4\n"
    "DE\t78267\tAach\tBaden-Württemberg\t08\tLandkreis Konstanz\t08335\t\t\t47.8\t8.8\t4\n"
)


# ---------------------------------------------------------------------------
# Bereinigungsfunktionen
# ---------------------------------------------------------------------------

def test_clean_plz_normalizes_leading_zeros():
    assert plzmod.clean_plz("1054") == "01054"
    assert plzmod.clean_plz(" 26810 ") == "26810"


def test_clean_plz_rejects_invalid_values():
    assert plzmod.clean_plz("") is None
    assert plzmod.clean_plz(None) is None
    assert plzmod.clean_plz("ABCDEF") is None  # keine Ziffern übrig


def test_clean_text_normalizes_whitespace():
    assert plzmod.clean_text("  Bad   Example  ") == "Bad Example"
    assert plzmod.clean_text(None) == ""


def test_clean_float_handles_invalid_values():
    assert plzmod.clean_float("51.1234") == pytest.approx(51.1234)
    assert plzmod.clean_float("") is None
    assert plzmod.clean_float(None) is None
    assert plzmod.clean_float("nicht-numerisch") is None


# ---------------------------------------------------------------------------
# CSV-Parser (suche-postleitzahl.org-Format)
# ---------------------------------------------------------------------------

def test_parse_suche_plz_csv_deduplicates_exact_duplicates():
    rows = plzmod.parse_suche_plz_csv(SAMPLE_SUCHE_PLZ_CSV)
    plz_78267 = [r for r in rows if r["plz"] == "78267"]
    assert len(plz_78267) == 1  # exakte Dublette (Zeile 3+4) wurde entfernt


def test_parse_suche_plz_csv_keeps_multi_assignment_as_separate_rows():
    rows = plzmod.parse_suche_plz_csv(SAMPLE_SUCHE_PLZ_CSV)
    plz_01454 = [r for r in rows if r["plz"] == "01454"]
    assert {r["ort"] for r in plz_01454} == {"Radeberg", "Wachau"}


def test_parse_suche_plz_csv_drops_incomplete_rows():
    rows = plzmod.parse_suche_plz_csv(SAMPLE_SUCHE_PLZ_CSV)
    # Zeile mit leerem "ort" (PLZ 99999) darf nicht im Ergebnis auftauchen
    assert all(r["plz"] != "99999" for r in rows)


def test_parse_suche_plz_csv_normalizes_plz_and_text():
    rows = plzmod.parse_suche_plz_csv(SAMPLE_SUCHE_PLZ_CSV)
    musterstadt = next(r for r in rows if r["ort"] == "Musterstadt")
    assert musterstadt["plz"] == "01234"


def test_parse_suche_plz_csv_missing_required_column_raises():
    bad_csv = "ort,plz\nFoo,12345\n"
    with pytest.raises(ValueError):
        plzmod.parse_suche_plz_csv(bad_csv)


# ---------------------------------------------------------------------------
# GeoNames-Parser
# ---------------------------------------------------------------------------

def test_parse_geonames_extracts_expected_fields():
    rows = plzmod.parse_geonames(SAMPLE_GEONAMES_TXT)
    assert len(rows) == 3
    radeberg = next(r for r in rows if r["ort"] == "Radeberg")
    assert radeberg["plz"] == "01454"
    assert radeberg["bundesland"] == "Sachsen"
    assert radeberg["landkreis"] == "Landkreis Bautzen"
    assert radeberg["lat"] == pytest.approx(51.1)


# ---------------------------------------------------------------------------
# Datenbank-Aufbau (schema.sql + build_database)
# ---------------------------------------------------------------------------

def test_build_database_creates_expected_1_to_n_relation(tmp_path):
    rows = plzmod.parse_suche_plz_csv(SAMPLE_SUCHE_PLZ_CSV)
    db_path = tmp_path / "test.sqlite3"

    plzmod.build_database(rows, db_path=db_path)
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        orte = conn.execute(
            """
            SELECT o.name FROM ort o
            JOIN plz p ON p.id = o.plz_id
            WHERE p.plz = '01454'
            ORDER BY o.name
            """
        ).fetchall()
        assert [o[0] for o in orte] == ["Radeberg", "Wachau"]

        anzahl_bundeslaender = conn.execute("SELECT COUNT(*) FROM bundesland").fetchone()[0]
        assert anzahl_bundeslaender == 4  # Sachsen, Baden-Württemberg, Niedersachsen, Bayern
    finally:
        conn.close()


def test_build_database_view_v_plz_orte_aggregates_correctly(tmp_path):
    rows = plzmod.parse_suche_plz_csv(SAMPLE_SUCHE_PLZ_CSV)
    db_path = tmp_path / "test.sqlite3"
    plzmod.build_database(rows, db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        view_row = conn.execute(
            "SELECT anzahl_orte, orte_liste FROM v_plz_orte WHERE plz = '01454'"
        ).fetchone()
        assert view_row is not None
        anzahl_orte, orte_liste = view_row
        assert anzahl_orte == 2
        assert "Radeberg" in orte_liste and "Wachau" in orte_liste
    finally:
        conn.close()


def test_build_database_rejects_invalid_plz_via_check_constraint(tmp_path):
    """Das CHECK-Constraint in schema.sql lässt nur 5-stellige, rein numerische PLZ zu."""
    db_path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(plzmod.SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO plz(plz) VALUES ('12A45')")
    conn.close()


# ---------------------------------------------------------------------------
# Dateiformat-Erkennung
# ---------------------------------------------------------------------------

def test_load_local_file_detects_csv_format(tmp_path):
    csv_path = tmp_path / "zuordnung_plz_ort.csv"
    csv_path.write_text(SAMPLE_SUCHE_PLZ_CSV, encoding="utf-8")

    text, fmt = plzmod.load_local_file(str(csv_path))
    assert fmt == "csv"
    assert "Radeberg" in text
