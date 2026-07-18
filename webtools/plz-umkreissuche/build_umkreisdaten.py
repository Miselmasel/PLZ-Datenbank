# -*- coding: utf-8 -*-
"""
Erstellt die kompakte Datengrundlage fuer die PLZ-Umkreissuche
(Suchmaske: PLZ + Umkreis -> Liste aller PLZ/Orte im Radius).

Fuehrt zwei oeffentliche Quellen zusammen:

1. Geokoordinaten je PLZ (geografischer Mittelpunkt):
   https://raw.githubusercontent.com/WZBSocialScienceCenter/plz_geocoord/master/plz_geocoord.csv
   (Apache-2.0, ermittelt via Google Geocoding API, Stand 01/2019)

2. Einwohnerzahl je PLZ (Zensus 2011, Registerzensus):
   https://zenodo.org/records/3600478 -> PlZ_AA_Kreis_Einwohner.csv
   (CC-BY-4.0, Tim M. Schendzielorz, Stand 2019)

Ergebnis: data/plz_umkreisdaten.json mit einer Zeile pro PLZ:
{plz, ort, bundesland, lat, lon, einwohner}

Dieses JSON wird von der statischen Web-Suchmaske geladen; die gesamte
Umkreisberechnung (Haversine) laeuft anschliessend clientseitig im Browser.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path

GEOCOORD_URL = (
    "https://raw.githubusercontent.com/WZBSocialScienceCenter/"
    "plz_geocoord/master/plz_geocoord.csv"
)
EINWOHNER_URL = "https://zenodo.org/api/records/3600478/files/PlZ_AA_Kreis_Einwohner.csv/content"

OUTPUT_PATH = Path(__file__).parent / "plz-umkreissuche" / "data" / "plz_umkreisdaten.json"


def _download(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "plz-umkreissuche/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8-sig")


def load_geocoord() -> dict[str, tuple[float, float]]:
    """Liest PLZ -> (lat, lon)."""
    text = _download(GEOCOORD_URL)
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    assert header == ["", "lat", "lng"], f"Unerwartete Spalten: {header}"
    result: dict[str, tuple[float, float]] = {}
    for row in reader:
        if len(row) != 3:
            continue
        plz, lat, lon = row
        plz = plz.strip().zfill(5)
        try:
            result[plz] = (float(lat), float(lon))
        except ValueError:
            continue
    return result


def load_einwohner() -> dict[str, dict]:
    """Liest PLZ -> {ort, bundesland, einwohner}."""
    text = _download(EINWOHNER_URL)
    reader = csv.DictReader(io.StringIO(text))
    result: dict[str, dict] = {}
    for row in reader:
        plz = (row.get("plz") or "").strip().zfill(5)
        if len(plz) != 5 or not plz.isdigit():
            continue
        try:
            einwohner = int(row["einwohner"])
        except (KeyError, ValueError):
            continue
        result[plz] = {
            "ort": (row.get("ort") or "").strip(),
            "bundesland": (row.get("bundesland") or "").strip(),
            "einwohner": einwohner,
        }
    return result


def build() -> list[dict]:
    print("Lade Geokoordinaten...")
    geo = load_geocoord()
    print(f"  {len(geo)} PLZ mit Koordinaten")

    print("Lade Einwohnerdaten...")
    einwohner = load_einwohner()
    print(f"  {len(einwohner)} PLZ mit Einwohnerangabe")

    merged: list[dict] = []
    for plz, (lat, lon) in geo.items():
        info = einwohner.get(plz)
        if info is None:
            continue
        merged.append(
            {
                "plz": plz,
                "ort": info["ort"],
                "bundesland": info["bundesland"],
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "einwohner": info["einwohner"],
            }
        )

    merged.sort(key=lambda r: r["plz"])
    print(f"Zusammengefuehrt: {len(merged)} PLZ mit Geodaten + Einwohnerzahl")
    return merged


def main() -> None:
    data = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"Geschrieben: {OUTPUT_PATH} ({size_kb:.0f} KB, {len(data)} Einträge)")


if __name__ == "__main__":
    main()
