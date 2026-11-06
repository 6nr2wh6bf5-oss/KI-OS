# Einbau ENERGIE + SPANNUNGSFALL in den World Monitor (Server /opt/world-monitor)

Stand 2026-11-03. Paket offline getestet (Mock-Daten, Python 3, nur Standardbibliothek). Live-Abrufe erst auf dem Server prüfbar.

## Dateien
| Datei | Zweck |
| --- | --- |
| `wm_common.py` | HTTP, Google-News-RSS, Zählen, Verlauf |
| `energie.py` + `energie_manuell.json` | Modul Energie (12 Indikatoren, Index 0-100, Stufe 1-5) |
| `spannungsfall.py` + `spannungsfall_indikatoren.json` | Themenfeld Aufrüstung DE/NATO und Spannungsfall (22 Indikatoren) |
| `panel_energie_spannungsfall.js` | Anzeige-Panels (Desktop und Mobil), keine Abhängigkeiten |

## Schritte (ein Durchgang)
1. Backup in neuen Ordner `_backup_2026-11-xx_energie_spannungsfall`.
2. Dateien nach `/opt/world-monitor/` kopieren (JSON-Dateien neben die .py). Datenordner: Umgebungsvariable `WM_DATA_DIR` oder Standard `./data`. `WM_CONFIG` auf die bestehende `config.json` zeigen lassen.
3. Optional in `config.json`: `"agsi_key": "..."` (kostenlos, agsi.gie.eu). Ohne Key: Gasspeicher als Datenlücke markiert.
4. `server.py`:
   - Hintergrund-Thread/Timer: `energie.update()` alle 30 Min., `spannungsfall.update()` alle 2 h (interne Sperre verhindert Mehrfachabrufe). Optional bestehende Feed-Meldungen übergeben: `update(news_items=[{titel, zeit(ISO), link, quelle}])`.
   - Routen `GET /api/energie` -> `energie.get_state()`, `GET /api/spannungsfall` -> `spannungsfall.get_state()` (gzip wie bisher).
   - Frühwarnung: `energie.fruehwarnung_signale()` und `spannungsfall.fruehwarnung_signale()` an die bestehende Liste anhängen (Felder bereich, titel, stufe 1-5, text, quelle; ggf. auf bestehendes Schema mappen).
   - HEIMATSCHUTZ-Ampeln: `heimat_beitrag()` beider Module liefert Punkte DE/CH (Energie max. 20, Spannungsfall max. 20 DE / 10 CH) zusätzlich zu den bestehenden Faktoren.
   - Veränderungen-Panel (24h/7d): `spannungsfall.get_state()["ereignisse"]` einspeisen.
5. Lage 10:00 / 22:00 (Haiku): an den Prompt anhängen `energie.lage_kontext()` + `spannungsfall.lage_kontext()` + `spannungsfall.LAGE_ANWEISUNG`. Mehrkosten ca. 600 Eingabe-Token pro Lage (vernachlässigbar). Conrad-Sprachfassung übernimmt die neuen Abschnitte automatisch.
6. Jarvis-Chat: neues Tool `energie_spannungsfall` (gibt beide `lage_kontext()` zurück), damit Fragen wie «Wie ist die Energielage?» beantwortet werden.
7. `index.html`: `<div id="panel-energie">` und `<div id="panel-spannungsfall">` in die rechte Spalte (Desktop) bzw. neuer Mobil-Tab «Energie/DE» oder in Tab «Heimat»; Script einbinden. Auf Überlappung rechte Spalte achten (offener Punkt aus Layout-Thread).
8. Optional Karte: Ebene «ENERGIE» (Gasspeicher DE/EU, Speicherseen CH als Länder-Färbung; Meldungen Stromausfall als Punkte, wenn ortbar).
9. Version erhöhen, Dienst neu starten, `curl /api/energie` und `/api/spannungsfall` prüfen, Datenlücken notieren, PC-Kopie synchronisieren.

## Bewertungslogik (Kurzfassung)
- Indikatorstufe 0-4. Spannungsfall: effektive Stufe = max(manuelle Basis, Meldungsstufe); +1 bei Anomalie (>= 2x Mittel der Vorwochen).
- Formelle Auslöser D1-D6 (NATO Art. 4/5, Art. 80a/115a GG, § 2 WPflG) **nur manuell**; Meldungen erzeugen nur einen Prüfhinweis. Gesetzte Auslöser erzwingen Mindest-Gesamtstufe (z.B. Spannungsfall -> 5).
- Zwei Teilindizes: AUFRÜSTUNG (strukturell) und ESKALATION (akut). Gesamt = 75 % Eskalation + 25 % Aufrüstung, Schwellen 20/50/65/80.
- Basisbewertungen älter als 60 Tage werden als «veraltet» markiert -> neu bewerten (Katalog-JSON, Feld `basis`).
- Energie: Index = 60 % gewichtetes Mittel + 40 % höchste Stufe; Schwellen in `energie.py` (z.B. TTF 40/60/100/180 EUR/MWh, Gasspeicher-Abweichung zur Referenz 5/12/20/30 Pp).

## Nicht verifiziert (auf Server prüfen)
- Endpunkt `api.energy-charts.info/frequency` (Feldname), BFE-CSV-URL Speicherseen (in config `bfe_speicherseen_csv` überschreibbar), AGSI-Feldnamen.
- Google News RSS liefert max. ca. 100 Treffer je Suche; Schwellen nach 2-4 Wochen Betrieb kalibrieren.
