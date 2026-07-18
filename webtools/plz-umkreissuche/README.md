# PLZ-Umkreissuche

Statisches Web-Werkzeug für die Umkreissuche von Postleitzahlen. Man gibt eine
Postleitzahl und einen Radius (in km) ein und erhält alle Postleitzahlen/Orte
im Umkreis — inklusive Bundesland, Luftlinien-Entfernung und Einwohnerzahl
(in Tausend). Die Ergebnisse lassen sich nach PLZ, Entfernung oder
Einwohnerzahl (auf- oder absteigend) sortieren und als CSV-Datei
herunterladen (Semikolon-getrennt, UTF-8 mit BOM, deutsches Zahlenformat —
öffnet direkt korrekt in Excel).

## Funktionsweise

Reines Frontend (HTML/CSS/Vanilla JS), keine Server-Logik nötig. Die
Distanzberechnung (Haversine-Formel, Erdradius 6371 km) läuft direkt im
Browser auf Basis der vorab generierten Datei `data/plz_umkreisdaten.json`.

- `index.html` — Seitenstruktur, Suchformular, Ergebnistabelle
- `css/style.css` — Design (Hell-/Dunkelmodus, responsive für Mobile)
- `js/app.js` — Laden der Daten, Umkreis-Filter, Sortierung, Rendering
- `data/plz_umkreisdaten.json` — vorberechneter Datensatz (PLZ, Ort,
  Bundesland, Koordinaten, Einwohnerzahl)
- `build_umkreisdaten.py` — Skript zum (Neu-)Erzeugen von
  `plz_umkreisdaten.json` aus den unten genannten Quellen

## Lokal starten

Da die Seite die JSON-Datei per `fetch` lädt, muss sie über einen lokalen
Webserver aufgerufen werden (nicht per `file://`):

```bash
cd webtools/plz-umkreissuche
python3 -m http.server 5000
# dann im Browser: http://localhost:5000
```

## Datensatz aktualisieren

```bash
cd webtools/plz-umkreissuche
python3 build_umkreisdaten.py
```

Lädt beide Quellen neu herunter, führt sie zusammen und schreibt
`data/plz_umkreisdaten.json`.

## Datengrundlage

- Geokoordinaten: [WZBSocialScienceCenter/plz_geocoord](https://github.com/WZBSocialScienceCenter/plz_geocoord)
  (Apache-2.0), Stand 2019-01-07
- Einwohnerzahlen: [Zenodo-Datensatz 3600478](https://zenodo.org/records/3600478)
  von Tim M. Schendzielorz (CC-BY-4.0), basierend auf Zensus 2011

Der zusammengeführte Datensatz deckt die Schnittmenge beider Quellen ab
(ca. 8.092 von ~8.300 deutschen Postleitzahlen). PLZ ohne Einwohnerdaten in
einer der beiden Quellen fehlen im Ergebnis.

## Hinweis

Dieses Werkzeug ist eigenständig und verwendet ein separates JSON-Datenmodell.
Es ist unabhängig vom SQLite-Schema (`schema.sql`) im Hauptprojekt.
