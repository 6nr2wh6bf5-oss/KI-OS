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

# Einbau PUSH-MELDUNGEN (ntfy) in den World Monitor

Stand 2026-11-06. `push.py` neben `server.py` legen. Der ntfy-Kanal steht nur in der `config.json` auf dem Server, nie im Repo.

## config.json
```json
"push": {"dienst": "ntfy", "ntfy_topic": "<langer Zufallsname>", "ntfy_server": "https://ntfy.sh",
         "max_pro_tag": 3, "ruhe_von": 23, "ruhe_bis": 7}
```
Optional `"fruehwarn_min_dauer_min"` (Standard 60). Die Ruhezeit gilt in Serverzeit; der Server läuft auf Europe/Zurich.

## server.py
```python
import push   # bei den anderen Modul-Importen, nach dem Setzen von WM_DATA_DIR/WM_CONFIG

PUSH_SPERRE = asyncio.Lock()

async def push_lauf(mit_fruehwarnung: bool):
    """Push-Meldungen pruefen (push.py). Ein Fehler hier darf den Monitor nie stoeren."""
    try:
        anomalien = None
        if mit_fruehwarnung:
            an = await api_anomalien()
            if "schnappschuesse" in an:   # sonst Ersatzantwort nach Fehler: nicht auswerten
                anomalien = an["anomalien"]
        async with PUSH_SPERRE:
            neu = await asyncio.to_thread(push.lauf, anomalien, _modul_state(energie), _modul_state(spannungsfall))
        for e in neu:
            print(f"[monitor] Push gesendet: {e['titel']}", flush=True)
    except Exception as e:
        print(f"[monitor] Push: {e}", flush=True)
```
Aufrufe: `await push_lauf(True)` in `fw_loop` nach dem `try/except`, vor `FW_STATE["zyklus"] += 1`; `await push_lauf(False)` in `energie_spannung_loop` nach der `for`-Schleife, vor `n += 1`.

Fehlerkorrektur in `fw_eval_series`: Die Finanz-Reihe braucht `"filter": []`. Fehlt das Feld, bricht `fw_filter` mit `KeyError: 'filter'` ab, sobald eine Finanz-Anomalie aktiv ist, und die ganze Frühwarnung bleibt leer.

## Regel
- Frühwarnung: nur Konvergenz (Stufe «stark», Aussagekraft «hoch», mehrere unabhängige Signale zum selben Konflikt), die mindestens 60 Minuten ununterbrochen besteht. Einzelne Anomalien melden sich nicht, auch nicht bei «stark» und «hoch».
- Energie und Spannungsfall: Gesamtstufe ab 4 oder Sprung um mindestens 2 Stufen; formelle Auslöser D1-D6 immer, auch nachts.
- Jede Meldung höchstens einmal in 7 Tagen. Unter Stufe 5 wartet eine Meldung die Ruhezeit ab und kommt danach, wenn sie noch gilt.
- Dateien in `WM_DATA_DIR`: `push_log.json` (gesendet), `push_vorher.json` (Stufen und Beobachtungszeiten).

## Rückrechnung
`push.lauf(..., dry_run=True, log_datei=..., zustand_datei=...)` sendet nichts und lässt das echte Log unberührt.
Stundenläufe 31.10.-06.11. (5,4 Tage, davon 25 Läufe ohne Frühwarn-Daten wegen des Fehlers oben): ursprüngliche Regel (jede Anomalie «stark» und «hoch», 24-h-Sperre) 8 Meldungen, rund 10 pro Woche; neue Regel 1-2 Meldungen, davon 0 aus den Modulen.

## Prüfen
Auf dem Server `python3 push.py` schickt die Testmeldung «World Monitor: Testmeldung». Neue Version setzen, Dienst neu starten, im Log nach `Push` suchen.
