# Deutsche PLZ-Datenbank (PLZ ↔ Ort ↔ Bundesland)

[![Tests](https://github.com/Miselmasel/PLZ-Datenbank/actions/workflows/tests.yml/badge.svg)](https://github.com/Miselmasel/PLZ-Datenbank/actions/workflows/tests.yml)

Enthält:

- **`schema.sql`** – normalisiertes SQL-Schema (SQLite, mit Hinweisen für PostgreSQL/MySQL)
- **`import_plz_data.py`** – Python-Skript, das eine öffentliche CSV lädt, bereinigt, Mehrfachzuordnungen (mehrere Orte pro PLZ) zusammenfasst und in die Datenbank importiert
- **`tests/`** – automatisierte Tests (pytest), die bei jedem Push/Pull-Request per GitHub Actions laufen

Keine externen Abhängigkeiten für den Betrieb nötig – nur die Python-Standardbibliothek (`csv`, `sqlite3`, `urllib`, `zipfile`). Für die Tests wird lediglich `pytest` benötigt.

## Datenmodell

```
bundesland (id, name)
plz        (id, plz)              -- eindeutige Postleitzahlen
ort        (id, plz_id, name,     -- 1:n zu plz: mehrere Orte pro PLZ möglich
            bundesland_id, landkreis, lat, lon, quelle_id)
```

Statt Orte als kommaseparierte Liste direkt in der PLZ-Zeile zu speichern, ist die
1:n-Relation über eine eigene `ort`-Tabelle mit Fremdschlüssel `plz_id` gelöst –
das ist die saubere relationale Variante und lässt sich beliebig indizieren/filtern.
Wer die Liste trotzdem bequem als String braucht, nutzt die View `v_plz_orte`:

```sql
SELECT * FROM v_plz_orte WHERE plz = '26810';
-- plz | orte_liste | bundeslaender | anzahl_orte
```

## Datenquelle

Das Skript versucht zwei Quellen, in dieser Reihenfolge:

1. **suche-postleitzahl.org** (`zuordnung_plz_ort.csv`, Datenbasis OpenStreetMap-Mitwirkende,
   Spalten `osm_id,ort,plz,bundesland`) – liefert echte Gemeinde-Namen, keine
   Firmenadressen. Die Website ist per Cloudflare gegen automatisierte Downloads
   abgesichert, ein direkter Skript-Download schlägt daher meist mit HTTP 403 fehl.
   **Empfehlung für beste Datenqualität:** Datei einmalig manuell im Browser laden
   unter [suche-postleitzahl.org/downloads](https://www.suche-postleitzahl.org/downloads)
   und dem Skript als Argument übergeben:
   ```bash
   python import_plz_data.py zuordnung_plz_ort.csv
   ```
2. **GeoNames** (`DE.zip`, [download.geonames.org/export/zip/DE.zip](https://download.geonames.org/export/zip/DE.zip)) –
   funktioniert ohne Cloudflare-Hürde und wird automatisch als Fallback genutzt,
   wenn Schritt 1 fehlschlägt. Achtung: GeoNames listet für manche PLZ auch
   Firmen-/Großkunden-Adressen (z.B. Behörden, Banken) als eigenen "Ortsnamen"
   statt nur echter Gemeinden – für eine Produktivanwendung ist Quelle 1 daher
   meist die genauere Wahl.

Beide Formate werden vom Skript automatisch erkannt (Spaltenname bzw. Tab- vs.
Komma-Trennung), du musst nichts manuell umstellen.

## Verwendung

```bash
# Variante A: vollautomatisch (versucht Quelle 1, fällt sonst auf GeoNames zurück)
python import_plz_data.py

# Variante B: manuell heruntergeladene CSV von suche-postleitzahl.org (empfohlen)
python import_plz_data.py zuordnung_plz_ort.csv

# Variante C: bereits heruntergeladenes GeoNames-Archiv
python import_plz_data.py DE.zip
```

Ergebnis: `plz_datenbank.sqlite3` im selben Verzeichnis. Das Skript druckt am
Ende automatisch drei Beispielabfragen zur Kontrolle.

## Regelmäßige automatische Aktualisierung

`update_plz_datenbank.py` hält `plz_datenbank.sqlite3` dauerhaft aktuell und
ist für wiederholte, unbeaufsichtigte Ausführung gebaut (Cron, Task Scheduler,
GitHub Actions):

```bash
python update_plz_datenbank.py                  # automatische Quellenwahl
python update_plz_datenbank.py --csv datei.csv   # lokale CSV/ZIP erzwingen
python update_plz_datenbank.py --force           # Sicherheitscheck überspringen
```

Was dabei passiert:

1. Lädt frische Daten (gleiche Quellen-Logik wie `import_plz_data.py`).
2. Baut daraus eine **neue** Datenbank in einer temporären Datei – die
   produktive Datenbank bleibt währenddessen unangetastet.
3. **Sicherheitscheck:** Fällt die neue Datenbank drastisch kleiner aus als
   die bisherige (Standard: weniger als 90 % der Orte-Zeilen), wird der
   Austausch abgebrochen (Exit-Code 1) – das schützt vor einer defekten oder
   unvollständigen Quelle. Mit `--force` lässt sich das übergehen.
4. Legt vor jedem Austausch ein Backup der alten Datenbank in `backups/` an
   (rotierend, Standard: die letzten 5 Läufe) und tauscht dann atomar.
5. Protokolliert jeden Lauf als eine Zeile in `update_log.jsonl`
   (Zeitstempel, Quelle, Kennzahlen vorher/nachher, Status).

Exit-Code `0` = erfolgreich aktualisiert oder unverändert, `1` = Fehler/Abbruch.

### Automatisch per Cron/Task Scheduler

```bash
# Linux/macOS (crontab -e), jeden Montag 06:00 Uhr:
0 6 * * 1 cd /pfad/zum/repo && /usr/bin/python3 update_plz_datenbank.py >> logs/cron.log 2>&1
```

Unter Windows lässt sich dieselbe Datei über die Aufgabenplanung (Task
Scheduler) mit `python.exe` als Aktion und dem Skriptpfad als Argument
einrichten.

### Automatisch per GitHub Actions

Die Workflow-Datei [`.github/workflows/update-database.yml`](.github/workflows/update-database.yml)
führt `update_plz_datenbank.py` standardmäßig **jeden Montag 04:00 UTC**
aus (per `cron`-Ausdruck anpassbar, z.B. täglich oder monatlich) und lässt
sich zusätzlich jederzeit manuell über "Run workflow" im Actions-Tab
starten. Ändert sich die Datenbank, committet und pusht der Workflow
`plz_datenbank.sqlite3` sowie `update_log.jsonl` automatisch zurück ins
Repository; bei einem Abbruch/Fehler schlägt der Workflow-Lauf sichtbar fehl.

> Hinweis: Dadurch wandert die kompilierte SQLite-Datei ins Git-Verlaufsprotokoll.
> Bei sehr häufigen Läufen (z.B. täglich über Jahre) wächst die Repo-Größe
> entsprechend. Wer das vermeiden will, kann den Commit/Push-Schritt im
> Workflow durch einen Upload als GitHub-Release-Asset ersetzen.

## Bereinigung, die das Skript durchführt

- PLZ wird auf exakt 5 Ziffern normalisiert (führende Nullen bleiben erhalten,
  z.B. `1054` → `01054`)
- Whitespace in Ort-/Bundesland-Namen wird vereinheitlicht
- Zeilen mit fehlender PLZ, Ort oder Bundesland werden verworfen
- Echte Dubletten (identische Kombination PLZ + Ort + Bundesland) werden
  entfernt – zusätzlich verhindert ein `UNIQUE`-Constraint in der Tabelle
  `ort`, dass sie überhaupt in die Datenbank gelangen
- Mehrfachzuordnungen (mehrere unterschiedliche Orte an derselben PLZ)
  bleiben bewusst als separate Zeilen in `ort` erhalten – das *ist* die
  gewünschte 1:n-Relation, keine zu bereinigende "Dublette"

## Eigene Abfragen in deiner Anwendung

```sql
-- Alle Orte zu einer PLZ
SELECT o.name, b.name AS bundesland
FROM ort o
JOIN plz p ON p.id = o.plz_id
JOIN bundesland b ON b.id = o.bundesland_id
WHERE p.plz = '26810';

-- Alle PLZ zu einem Ortsnamen
SELECT p.plz, b.name AS bundesland
FROM ort o
JOIN plz p ON p.id = o.plz_id
JOIN bundesland b ON b.id = o.bundesland_id
WHERE o.name = 'Westoverledingen';

-- Schnelle Liste über die View
SELECT * FROM v_plz_orte WHERE plz = '26810';
```

## Tests

```bash
pip install pytest
pytest -v
```

Die Tests arbeiten mit kleinen, lokalen Beispieldaten (kein Netzwerkzugriff) und prüfen:

- Bereinigungsfunktionen (`clean_plz`, `clean_text`, `clean_float`)
- Beide CSV-Parser (suche-postleitzahl.org- und GeoNames-Format), inkl. Dublettenfilter und Mehrfachzuordnung
- Den kompletten Datenbankaufbau aus `schema.sql` inkl. der 1:n-Relation und der View `v_plz_orte`
- Die `CHECK`-Constraint der PLZ-Spalte

Die GitHub-Actions-Workflow-Datei [`.github/workflows/tests.yml`](.github/workflows/tests.yml) führt diese Tests automatisch bei jedem Push und Pull-Request auf `main` aus (Python 3.10–3.13) und prüft zusätzlich, dass `schema.sql` fehlerfrei ausgeführt werden kann.

## Lizenzhinweis

Bei Nutzung der suche-postleitzahl.org-Daten (OpenStreetMap-Mitwirkende, ODbL 1.0)
im Impressum/in den Quellenangaben deiner Anwendung angeben, z.B.:
"Enthält Daten von OpenStreetMap-Mitwirkenden, ODbL 1.0 (via suche-postleitzahl.org)".
GeoNames-Daten stehen unter einer eigenen, ebenfalls attributionspflichtigen Lizenz
(siehe [geonames.org/export](https://www.geonames.org/export/)).
