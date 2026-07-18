#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_plz_data.py
===================

Lädt eine öffentliche PLZ/Ort/Bundesland-Zuordnung, bereinigt die Daten,
fasst Mehrfachzuordnungen (mehrere Orte pro PLZ) zusammen und importiert
alles in eine normalisierte SQLite-Datenbank gemäß schema.sql.

Unterstützte Datenquellen (automatische Erkennung):

  1) GeoNames (Standard, wird automatisch heruntergeladen, kein Login/
     Captcha nötig):
        https://download.geonames.org/export/zip/DE.zip
     Tab-getrennt, ohne Kopfzeile:
        country_code, postal_code, place_name, admin_name1 (Bundesland),
        admin_code1, admin_name2 (Landkreis/Regierungsbezirk), admin_code2,
        admin_name3, admin_code3, latitude, longitude, [accuracy]

  2) suche-postleitzahl.org "zuordnung_plz_ort.csv" (Datenbasis: OpenStreetMap-
     Mitwirkende). Die Seite ist per Cloudflare gegen automatisierte Downloads
     abgesichert -> bitte die Datei manuell im Browser laden:
        https://www.suche-postleitzahl.org/downloads
     und den Pfad als Kommandozeilenargument übergeben, z.B.:
        python import_plz_data.py zuordnung_plz_ort.csv
     Kommagetrennt, mit Kopfzeile: osm_id,ort,plz,bundesland
     Lizenz: OpenStreetMap-Daten (ODbL) -> bei Weiterverwendung Quelle nennen:
        "Enthält Daten von OpenStreetMap-Mitwirkenden, ODbL 1.0
        (via suche-postleitzahl.org)"

Verwendung:
    # Variante A: GeoNames automatisch laden (Standard, kein Argument nötig)
    python import_plz_data.py

    # Variante B: manuell heruntergeladene CSV von suche-postleitzahl.org
    python import_plz_data.py zuordnung_plz_ort.csv

    # Variante C: bereits heruntergeladenes GeoNames-Archiv
    python import_plz_data.py DE.zip

Ergebnis:
    plz_datenbank.sqlite3  (im aktuellen Arbeitsverzeichnis)

Nur Standardbibliothek nötig (csv, sqlite3, urllib, zipfile) - keine
externen Abhängigkeiten erforderlich.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

GEONAMES_URL = "https://download.geonames.org/export/zip/DE.zip"
SUCHE_PLZ_URL = "https://www.suche-postleitzahl.org/download_files/public/zuordnung_plz_ort.csv"
DB_PATH = Path(__file__).parent / "plz_datenbank.sqlite3"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

GEONAMES_FIELDS = [
    "country_code", "plz", "ort", "bundesland", "admin_code1",
    "landkreis", "admin_code2", "admin_name3", "admin_code3",
    "lat", "lon", "accuracy",
]


# ---------------------------------------------------------------------------
# 1. Rohdaten laden
# ---------------------------------------------------------------------------

def download_geonames_zip(url: str = GEONAMES_URL) -> bytes:
    print(f"Lade GeoNames-Archiv von {url} ...")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def try_download_suche_plz_csv(url: str = SUCHE_PLZ_URL) -> Optional[str]:
    """
    Versucht die CSV direkt von suche-postleitzahl.org zu laden. Die Seite
    nutzt einen Cloudflare-Bot-Schutz, der automatisierte Downloads häufig
    blockiert (HTTP 403). In diesem Fall wird None zurückgegeben und im
    Aufrufer auf den manuellen Download bzw. GeoNames als Fallback verwiesen.
    """
    try:
        print(f"Versuche Direkt-Download von {url} ...")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - bewusst breit, nur für Fallback-Logik
        print(f"  -> Direkt-Download nicht möglich ({exc}).")
        return None


def extract_de_txt(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with zf.open("DE.txt") as f:
            return f.read().decode("utf-8")


def load_local_file(path: str) -> tuple[str, str]:
    """Gibt (inhalt, format) zurück; format ist 'geonames_zip', 'geonames_txt' oder 'csv'."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        return extract_de_txt(p.read_bytes()), "geonames_txt"
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".csv":
        return text, "csv"
    # .txt: Inhalt anhand des Trennzeichens der ersten Zeile erkennen
    return text, ("geonames_txt" if "\t" in text.splitlines()[0] else "csv")


# ---------------------------------------------------------------------------
# 2. Bereinigung / gemeinsame Hilfsfunktionen
# ---------------------------------------------------------------------------

def clean_plz(value: Optional[str]) -> Optional[str]:
    """Normalisiert eine PLZ auf exakt 5 Ziffern (führende Nullen erhalten)."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value.strip())
    if not digits:
        return None
    digits = digits.zfill(5)
    return digits if len(digits) == 5 else None


def clean_text(value: Optional[str]) -> str:
    """Trimmt und normalisiert Whitespace in Textfeldern (Ort, Bundesland, ...)."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.strip())


def clean_float(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 3a. Parser: GeoNames (tab-getrennt, keine Kopfzeile)
# ---------------------------------------------------------------------------

def parse_geonames(text: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict] = []
    verworfen = 0

    for raw in reader:
        if not raw:
            continue
        record = dict(zip(GEONAMES_FIELDS, raw))

        plz = clean_plz(record.get("plz"))
        ort = clean_text(record.get("ort"))
        bundesland = clean_text(record.get("bundesland"))

        if not plz or not ort or not bundesland:
            verworfen += 1
            continue

        key = (plz, ort.lower(), bundesland.lower())
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "plz": plz,
            "ort": ort,
            "bundesland": bundesland,
            "landkreis": clean_text(record.get("landkreis")) or None,
            "lat": clean_float(record.get("lat")),
            "lon": clean_float(record.get("lon")),
            "quelle_id": None,
        })

    print(f"[GeoNames] {len(rows)} eindeutige Zeilen übernommen, {verworfen} unvollständige Zeilen verworfen.")
    return rows


# ---------------------------------------------------------------------------
# 3b. Parser: suche-postleitzahl.org (CSV, Kopfzeile osm_id,ort,plz,bundesland)
# ---------------------------------------------------------------------------

def parse_suche_plz_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    fieldmap = {name.lower().strip(): name for name in fieldnames}

    required = {"plz", "ort", "bundesland"}
    missing = required - set(fieldmap)
    if missing:
        raise ValueError(
            f"CSV fehlen erwartete Spalten: {missing}. Gefundene Spalten: {fieldnames}"
        )

    landkreis_key = fieldmap.get("landkreis")
    osm_key = fieldmap.get("osm_id")
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict] = []
    verworfen = 0

    for raw_row in reader:
        plz = clean_plz(raw_row.get(fieldmap["plz"]))
        ort = clean_text(raw_row.get(fieldmap["ort"]))
        bundesland = clean_text(raw_row.get(fieldmap["bundesland"]))

        if not plz or not ort or not bundesland:
            verworfen += 1
            continue

        osm_id = clean_text(raw_row.get(osm_key)) if osm_key else None

        key = (plz, ort.lower(), bundesland.lower())
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "plz": plz,
            "ort": ort,
            "bundesland": bundesland,
            "landkreis": clean_text(raw_row.get(landkreis_key)) or None if landkreis_key else None,
            "lat": None,
            "lon": None,
            "quelle_id": osm_id or None,
        })

    print(f"[suche-postleitzahl.org] {len(rows)} eindeutige Zeilen übernommen, {verworfen} unvollständige Zeilen verworfen.")
    return rows


# ---------------------------------------------------------------------------
# 4. Import in SQLite gemäß schema.sql
# ---------------------------------------------------------------------------

def build_database(rows: list[dict], db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    cur = conn.cursor()

    bundesland_cache: dict[str, int] = {}
    plz_cache: dict[str, int] = {}

    for row in rows:
        # -- Bundesland (nur einmal anlegen, dann Cache nutzen) --
        bl_name = row["bundesland"]
        bl_id = bundesland_cache.get(bl_name)
        if bl_id is None:
            cur.execute("INSERT OR IGNORE INTO bundesland(name) VALUES (?)", (bl_name,))
            bl_id = cur.execute(
                "SELECT id FROM bundesland WHERE name = ?", (bl_name,)
            ).fetchone()[0]
            bundesland_cache[bl_name] = bl_id

        # -- PLZ (nur einmal anlegen, dann Cache nutzen) --
        plz_val = row["plz"]
        plz_id = plz_cache.get(plz_val)
        if plz_id is None:
            cur.execute("INSERT OR IGNORE INTO plz(plz) VALUES (?)", (plz_val,))
            plz_id = cur.execute(
                "SELECT id FROM plz WHERE plz = ?", (plz_val,)
            ).fetchone()[0]
            plz_cache[plz_val] = plz_id

        # -- Ort (Mehrfachzuordnung: mehrere Orte je plz_id möglich) --
        cur.execute(
            """
            INSERT OR IGNORE INTO ort (plz_id, name, bundesland_id, landkreis, lat, lon, quelle_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (plz_id, row["ort"], bl_id, row["landkreis"], row["lat"], row["lon"], row["quelle_id"]),
        )

    conn.commit()

    n_plz = cur.execute("SELECT COUNT(*) FROM plz").fetchone()[0]
    n_ort = cur.execute("SELECT COUNT(*) FROM ort").fetchone()[0]
    n_bl = cur.execute("SELECT COUNT(*) FROM bundesland").fetchone()[0]
    n_multi = cur.execute(
        "SELECT COUNT(*) FROM (SELECT plz_id FROM ort GROUP BY plz_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]

    print("---------------------------------------------")
    print(f"Import abgeschlossen -> {db_path}")
    print(f"  Bundesländer : {n_bl}")
    print(f"  PLZ (eindeutig): {n_plz}")
    print(f"  Orte (Zeilen)  : {n_ort}")
    print(f"  PLZ mit mehreren Orten (Mehrfachzuordnung): {n_multi}")
    print("---------------------------------------------")

    conn.close()


# ---------------------------------------------------------------------------
# 5. Beispielabfragen (zur Kontrolle direkt nach dem Import)
# ---------------------------------------------------------------------------

def beispielabfragen(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)

    # Eine PLZ mit garantierter Mehrfachzuordnung ermitteln, um die
    # 1:n-Beziehung live zu demonstrieren.
    beispiel_plz = conn.execute(
        """
        SELECT p.plz FROM plz p JOIN ort o ON o.plz_id = p.id
        GROUP BY p.plz HAVING COUNT(*) > 1 LIMIT 1
        """
    ).fetchone()
    beispiel_plz = beispiel_plz[0] if beispiel_plz else "26802"

    print(f"\nBeispiel 1: Alle Orte zur PLZ '{beispiel_plz}' (per JOIN, 1:n):")
    for row in conn.execute(
        """
        SELECT p.plz, o.name AS ort, b.name AS bundesland
        FROM plz p
        JOIN ort o ON o.plz_id = p.id
        JOIN bundesland b ON b.id = o.bundesland_id
        WHERE p.plz = ?
        """,
        (beispiel_plz,),
    ):
        print(" ", row)

    print("\nBeispiel 2: Gleiche Abfrage über die komfortable View v_plz_orte:")
    for row in conn.execute("SELECT * FROM v_plz_orte WHERE plz = ?", (beispiel_plz,)):
        print(" ", row)

    print("\nBeispiel 3: Alle PLZ zum Ort 'Westoverledingen':")
    for row in conn.execute(
        """
        SELECT p.plz, o.name, b.name
        FROM ort o
        JOIN plz p ON p.id = o.plz_id
        JOIN bundesland b ON b.id = o.bundesland_id
        WHERE o.name LIKE ?
        """,
        ("%Westoverledingen%",),
    ):
        print(" ", row)

    conn.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1:
        text, fmt = load_local_file(sys.argv[1])
        print(f"Lese lokale Datei: {sys.argv[1]} (erkanntes Format: {fmt})")
    else:
        # 1) Bevorzugt: direkter Download von suche-postleitzahl.org
        #    (Gemeinde-genaue Ort-Zuordnung, siehe Modulbeschreibung).
        text = try_download_suche_plz_csv()
        if text is not None:
            fmt = "csv"
        else:
            # 2) Fallback: GeoNames, funktioniert ohne Cloudflare-Hürde.
            #    Hinweis: GeoNames führt für einige PLZ auch Firmen-/
            #    Großkunden-Adressen als eigenen "Ortsnamen", nicht nur
            #    Gemeinden. Für produktive Zwecke ist ein manueller
            #    CSV-Download von suche-postleitzahl.org/downloads und der
            #    Aufruf 'python import_plz_data.py zuordnung_plz_ort.csv'
            #    daher die genauere Alternative.
            print("Weiche auf GeoNames-Datensatz aus (automatischer Download, "
                  "kann vereinzelt Firmen-/Großkunden-PLZ statt reiner Gemeinde-"
                  "namen enthalten). Für Gemeinde-genaue Daten die CSV manuell "
                  "unter https://www.suche-postleitzahl.org/downloads laden und "
                  "per Kommandozeilenargument übergeben.")
            text = extract_de_txt(download_geonames_zip())
            fmt = "geonames_txt"

    rows = parse_geonames(text) if fmt == "geonames_txt" else parse_suche_plz_csv(text)

    print(f"{len(rows)} eindeutige PLZ/Ort/Bundesland-Zeilen nach Bereinigung.")
    build_database(rows)
    beispielabfragen()


if __name__ == "__main__":
    main()
