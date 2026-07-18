-- ============================================================
-- Deutsche PLZ-Datenbank: PLZ <-> Ort <-> Bundesland
-- Kompatibel mit SQLite (Standard). Hinweise für MySQL/PostgreSQL
-- stehen als Kommentare am Ende der Datei.
--
-- Design-Idee:
--   - Eine PLZ kann zu MEHREREN Orten gehören (Mehrfachzuordnung),
--     z.B. weil mehrere Gemeinden dieselbe PLZ teilen.
--   - Deshalb ist "ort" eine eigene Tabelle mit Fremdschlüssel auf
--     "plz" -> klassische 1:n-Beziehung (1 PLZ -> n Orte).
--   - "bundesland" ist ebenfalls ausgelagert, um Redundanz zu
--     vermeiden und Tippfehler/Varianten zu verhindern.
--   - Die View "v_plz_orte" liefert bei Bedarf die Orte als
--     kommaseparierte Liste pro PLZ (für einfache Abfragen).
-- ============================================================

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_plz_orte;
DROP TABLE IF EXISTS ort;
DROP TABLE IF EXISTS plz;
DROP TABLE IF EXISTS bundesland;

-- Bundesländer (16 Stück, Nachschlagetabelle)
CREATE TABLE bundesland (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

-- Eindeutige Postleitzahlen (5-stellig, führende Nullen erhalten)
CREATE TABLE plz (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    plz     TEXT NOT NULL UNIQUE CHECK (length(plz) = 5 AND plz GLOB '[0-9][0-9][0-9][0-9][0-9]')
);

-- Orte: 1:n-Relation zu plz (mehrere Orte pro PLZ möglich)
CREATE TABLE ort (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plz_id          INTEGER NOT NULL REFERENCES plz(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    bundesland_id   INTEGER NOT NULL REFERENCES bundesland(id),
    landkreis       TEXT,                    -- optional, falls Quelle es liefert
    lat             REAL,                    -- optional, Breitengrad
    lon             REAL,                    -- optional, Längengrad
    quelle_id       TEXT,                    -- optionale ID aus der Quelldatei (z.B. OSM-Relation)
    -- Verhindert echte Dubletten: gleiche PLZ + gleicher Ort + gleiches Bundesland nur 1x
    UNIQUE (plz_id, name, bundesland_id)
);

CREATE INDEX idx_ort_plz_id        ON ort(plz_id);
CREATE INDEX idx_ort_name          ON ort(name);
CREATE INDEX idx_ort_bundesland_id ON ort(bundesland_id);

-- Bequeme Sicht: pro PLZ alle zugehörigen Orte/Bundesländer als Liste
CREATE VIEW v_plz_orte AS
SELECT
    p.plz                                          AS plz,
    GROUP_CONCAT(DISTINCT o.name)                  AS orte_liste,
    GROUP_CONCAT(DISTINCT b.name)                  AS bundeslaender,
    COUNT(DISTINCT o.id)                           AS anzahl_orte
FROM plz p
JOIN ort o          ON o.plz_id = p.id
JOIN bundesland b   ON b.id = o.bundesland_id
GROUP BY p.plz;

-- ============================================================
-- Hinweise für PostgreSQL:
--   - INTEGER PRIMARY KEY AUTOINCREMENT  ->  SERIAL PRIMARY KEY / GENERATED ALWAYS AS IDENTITY
--   - GROUP_CONCAT(DISTINCT x)           ->  STRING_AGG(DISTINCT x, ', ')
--   - GLOB-Check                         ->  plz ~ '^[0-9]{5}$'
--
-- Hinweise für MySQL/MariaDB:
--   - INTEGER PRIMARY KEY AUTOINCREMENT  ->  INT PRIMARY KEY AUTO_INCREMENT
--   - GROUP_CONCAT funktioniert identisch
--   - CHECK-Constraint ab MySQL 8.0.16 unterstützt, sonst per Trigger/Anwendungslogik prüfen
-- ============================================================
