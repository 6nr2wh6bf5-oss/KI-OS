# Einbau OSTFLANKE (Baltikum, Suwalki-Korridor) in den World Monitor

Stand 2026-11-17. Offline mit Mock-Daten getestet (Python 3, nur Standardbibliothek). Live-Abrufe erst auf dem Server prüfbar.

## Dateien
| Datei | Zweck |
| --- | --- |
| `ostflanke.py` | Sammler, Felder wer/was/wie viel/wann/wohin, Bündelung, Status bestätigt/unbestätigt, ADS-B, NOTAM, AIS, Bewertung O1-O8 |
| `ostflanke_quellen.json` | 42 Quellen (offiziell LT/LV/EE/PL/FI/SE/DE/UK/US/CA/FR/NL/NATO, Eigenangaben RU/BY, Analyse, Medien), Orte, Indikatoren, Verknüpfung Spannungsfall |
| `panel_ostflanke.js` | Eigener Reiter: Karte, Ereignistabelle (Handy als Karten), Indikatoren, Technik |
| `spannungsfall.py` (geändert) | nimmt Ostflanken-Stufen auf (`extern`), liefert `folgen` |
| `spannungsfall_folgen.json` (neu) | Folgen für die Bevölkerung je Auslöser (Art. 80a/115a GG, EU), mit Fundstellen |
| `panel_energie_spannungsfall.js` (geändert) | Kennzeichnung «◆ Ostflanke», Block «Folgen für die Bevölkerung» |
| `push.py` (geändert) | Ostflanken-Alarm vorbereitet, **standardmässig aus** |

## Schritte
1. Backup `_backup_2026-11-xx_ostflanke`.
2. Dateien nach `/opt/world-monitor/` kopieren. Zuerst `python3 ostflanke.py --diagnose`: zeigt je Quelle, ob RSS oder Google News liefert. Quellen mit 0 Treffern über mehrere Tage im JSON anpassen.
3. `server.py`:
   - Timer alle 10 Min.: `ostflanke.update()` (ADS-B jedes Mal, Nachrichten intern höchstens stündlich). Optional `update(news_items=[...], llm_fn=haiku)`: `llm_fn(prompt)->str` präzisiert wer/was/wie viel/wohin aus Schlagzeilen (max. 12 neue je Lauf, ca. 4'000 Token/h).
   - Reihenfolge: zuerst `ostflanke.update()`, dann `spannungsfall.update()` (holt sich `ostflanke.spannungsfall_beitrag()` selbst).
   - Route `GET /api/ostflanke` -> `ostflanke.get_state()` (gzip, ohne interne Felder).
   - AIS: im bestehenden aisstream-Teil alle paar Minuten `ostflanke.ais_einspeisen([{mmsi, name, typ, lat, lon}, ...])` aufrufen (typ = AIS-Schiffstyp, 35 = Militär).
   - Frühwarnung: `ostflanke.fruehwarnung_signale()` anhängen (Feld `prioritaet: 1` -> oben einsortieren); `ostflanke.konvergenz_anomalie()` in die Konvergenzliste (trägt `kein_push`, solange der Alarm nicht freigegeben ist).
   - Push: `push.lauf(..., ostflanke_state=ostflanke.get_state())`. **Freigegeben am 17.11.2026 (Variante «ab Stufe 4 oder Sprung um 2»):** in config.json `"ostflanke": {"push_aktiv": true}` setzen. Es gelten die bestehenden Limits (max. 3/Tag, gleiche Meldung 1x/7 Tage, 23-7 Uhr nur Stufe 5); offiziell bestätigte formelle Schritte (Art. 4/5, Mobilmachung) immer.
4. Optional config.json: `"icao_api_key": "..."` (NOTAMs, ICAO API Data Service; Abruf alle 12 h, `ostflanke.notam_intervall_h`). Ohne Schlüssel: Datenlücke angezeigt.
5. Lage 10:00/22:00: `ostflanke.lage_kontext()` **vor** allen anderen Abschnitten in den Prompt, plus `ostflanke.LAGE_ANWEISUNG`. Jarvis-Tool `ostflanke` -> `lage_kontext()`.
6. `index.html`: Desktop neuer Reiter/Tab «Ostflanke» mit `<div id="panel-ostflanke">`, Handy neuer Tab «Ostflanke» als **erster** Tab. Script `panel_ostflanke.js` einbinden. Leaflet wird nachgeladen, falls die Seite es nicht schon hat (Kacheln CARTO dark).
7. Version erhöhen, Dienst neu starten, `curl /api/ostflanke` prüfen, Datenlücken notieren.

## Bewertung (Kurzfassung)
- Ereignis = gebündelte Meldungen (ähnlicher Titel, gleicher Ort oder gleiche Menge und Akteur, ±36 h).
- Status: «bestätigt (offiziell)» = Stelle A; «bestätigt (mehrere Quellen)» = ≥ 2 Verlage, davon einer A/B; «Eigenangabe RU/BY»; «unbestätigt (1 seriöse Quelle)»; «unbestätigt».
- Indikator = max(Basis manuell, Meldungsstufe gewichtet A 1,0 / B 0,7 / C 0,35, Technik), +1 bei Anomalie (≥ 2x Vorwochen). O8 (formell) nur manuell, Meldungen erzeugen Prüfhinweis.
- ESKALATION aus O1, O2, O4-O8; NATO-VERLEGUNG (O3) nur Anzeige. Gesamtstufe aus Eskalation, +1 bei starker Konvergenz (≥ 3 unabhängige Signalarten in 24 h, mind. eine offiziell oder technisch).
- Verknüpfung Spannungsfall: C3 ← max(O4, O5, O6), C4 ← max(O1, O2, O7), A5 ← O3, D1 nur Prüfhinweis aus O8.
- Basisbewertungen (Stand 17.11.2026) alle ≤ 60 Tage im JSON nachführen.

## Nicht verifiziert (auf Server prüfen)
- Direkte RSS-URLs kam.lt, mil.ee, gov.uk-Atom (sonst automatisch Google News).
- Ob Google News die `site:`-Suchen für alle Behördenseiten liefert (`--diagnose`).
- ICAO-NOTAM-Feldnamen (`iteme`, `itema`) gemäss Upstream-Code; Kontingent des Schlüssels.
- adsb.lol: Nutzungsbedingungen/Rate-Limit; Alternative `api.airplanes.live`.
