"""Modul SPANNUNGSFALL: Aufruestung Deutschland/NATO und Vorbereitung auf Spannungs-/Verteidigungsfall.

Logik
1. Katalog spannungsfall_indikatoren.json: je Indikator eine manuelle Basis-Bewertung (Stufe 0-4).
2. Meldungen (Google News RSS) je Indikator zaehlen (7 Tage) -> News-Stufe nach Schwellen,
   +1 Stufe bei Anomalie (>= 2x Mittel der Vorwochen).
3. Effektive Stufe = max(Basis, News). Ausnahme formelle Ausloeser (D*): nur Basis zaehlt,
   Meldungen erzeugen einen Pruefhinweis.
4. Zwei Teilindizes 0-100:
   - AUFRUESTUNG (strukturell, langfristig): Kategorien aufruestung + gesamtverteidigung
   - ESKALATION (akut): Kategorien bedrohung + ausloeser
   Gesamtstufe 1-5 = vor allem Eskalation (75 %), Aufruestung 25 %; formelle Ausloeser setzen Mindeststufen.
   Grund: Aufruestung allein ist Abschreckung, kein Kriegsindikator.
5. Verlauf taeglich (Indizes, Stufen, Meldungszahlen) -> Entwicklung, Trends, Ereignisliste.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from wm_common import (count_recent, fetch_news, iso, load_json, now_utc,
                       push_history, save_json, trend)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("WM_DATA_DIR", os.path.join(BASE, "data"))
STATE_FILE = os.path.join(DATA_DIR, "spannungsfall_state.json")
KATALOG_FILE = os.path.join(BASE, "spannungsfall_indikatoren.json")

GESAMT_TEXT = {
    1: "Normallage",
    2: "Erhöhte Wachsamkeit (strukturelle Aufrüstung, hybride Bedrohung)",
    3: "Angespannt (gehäufte Vorfälle, akute Vorbereitungen)",
    4: "Krisenvorbereitung (formelle Schritte eingeleitet)",
    5: "Spannungs-/Verteidigungsfall oder Bündnisfall",
}
VERALTET_TAGE = 60


def _alter_tage(datum: str) -> int:
    try:
        return (datetime.now() - datetime.strptime(datum, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return 999


def _news_stufe(n: int, schwellen: list[int]) -> int:
    s = 0
    for i, g in enumerate(schwellen, start=1):
        if n >= g:
            s = i
    return s


def _vorwochen_mittel(hist: list[dict], key: str) -> float | None:
    werte = []
    for w in (7, 14, 21, 28):
        ziel = (datetime.now() - timedelta(days=w)).strftime("%Y-%m-%d")
        kand = [h for h in hist if h["datum"] <= ziel and key in h.get("meldungen", {})]
        if kand:
            werte.append(kand[-1]["meldungen"][key])
    return sum(werte) / len(werte) if len(werte) >= 2 else None


def bewerte(katalog: dict, items: list[dict], hist: list[dict]) -> list[dict]:
    res = []
    for ind in katalog["indikatoren"]:
        nw = ind.get("news", {})
        eigene = [x for x in items if x.get("suchbegriff") in nw.get("suche", [])]
        n, treffer = count_recent(eigene, nw.get("muster", []), 7, nw.get("ausschluss"))
        ns = _news_stufe(n, nw.get("schwellen", [99, 99, 99, 99]))
        mittel = _vorwochen_mittel(hist, ind["id"])
        anomalie = bool(mittel and n >= max(3, nw.get("schwellen", [99])[0]) and n >= 2 * mittel)
        if anomalie:
            ns = min(4, ns + 1)
        basis = ind["basis"]
        formell = ind.get("formell", False)
        eff = basis["stufe"] if formell else max(basis["stufe"], ns)
        pruef = None
        if formell and ns >= 1:
            pruef = f"{n} Meldungen erwähnen '{ind['name']}' - formellen Status manuell prüfen."
        quelle_stufe = "Basis" if eff == basis["stufe"] else "Meldungen"
        res.append({
            "id": ind["id"], "kategorie": ind["kategorie"], "name": ind["name"],
            "gewicht": ind.get("gewicht", 1), "formell": formell,
            "stufe": eff, "basis_stufe": basis["stufe"], "news_stufe": ns, "stufe_aus": quelle_stufe,
            "kriterium": ind["kriterien"][eff] if eff < len(ind["kriterien"]) else "",
            "text": basis["text"], "quelle": basis.get("quelle", ""), "stand": basis.get("stand"),
            "veraltet": _alter_tage(basis.get("stand")) > VERALTET_TAGE,
            "meldungen_7t": n, "vorwochen_mittel": round(mittel, 1) if mittel is not None else None,
            "anomalie": anomalie, "pruefhinweis": pruef,
            "beispiele": [{"titel": t["titel"], "link": t["link"], "quelle": t["quelle"], "zeit": t["zeit"]}
                          for t in treffer[:4]],
            "gesamtstufe_min": ind.get("gesamtstufe_min"),
        })
    return res


def _teilindex(inds: list[dict], kats: set[str]) -> float:
    sel = [i for i in inds if i["kategorie"] in kats]
    if not sel:
        return 0.0
    w = sum(i["gewicht"] for i in sel)
    mittel = sum(i["gewicht"] * i["stufe"] for i in sel) / w / 4 * 100
    spitze = max(i["stufe"] for i in sel) * 25
    return round(0.7 * mittel + 0.3 * spitze, 1)


def gesamt(inds: list[dict], katalog: dict) -> dict:
    kat = katalog["kategorien"]
    auf = _teilindex(inds, {k for k, v in kat.items() if v["index"] == "aufruestung"})
    esk = _teilindex(inds, {k for k, v in kat.items() if v["index"] == "eskalation"})
    kombi = round(0.75 * esk + 0.25 * auf, 1)
    # Eigene Schwellen: strukturelle Aufruestung + hybride Lage ergibt Stufe 2; Stufe 3 erst bei akuter Haeufung
    stufe = 1 if kombi < 20 else 2 if kombi < 50 else 3 if kombi < 65 else 4 if kombi < 80 else 5
    grund = "Index"
    for i in inds:
        if i["formell"] and i["stufe"] >= 3 and i.get("gesamtstufe_min") and i["gesamtstufe_min"] > stufe:
            stufe, grund = i["gesamtstufe_min"], f"Auslöser {i['id']} {i['name']}"
    return {"aufruestung": auf, "eskalation": esk, "kombi": kombi, "stufe": stufe,
            "stufe_text": GESAMT_TEXT[stufe], "stufe_grund": grund,
            "kategorien": {k: _teilindex(inds, {k}) for k in kat}}


def _ereignisse(alt: dict, neu_inds: list[dict], log: list[dict]) -> list[dict]:
    vorher = {i["id"]: i["stufe"] for i in alt.get("indikatoren", [])}
    heute = datetime.now().strftime("%Y-%m-%d")
    for i in neu_inds:
        v = vorher.get(i["id"])
        if v is not None and v != i["stufe"]:
            log.append({"datum": heute, "id": i["id"], "name": i["name"], "von": v, "nach": i["stufe"],
                        "grund": i["stufe_aus"]})
        if i["pruefhinweis"] and not any(e.get("pruef") == i["id"] and e["datum"] == heute for e in log):
            log.append({"datum": heute, "id": i["id"], "name": i["name"], "pruef": i["id"], "text": i["pruefhinweis"]})
    return log[-200:]


def update(force: bool = False, news_items: list[dict] | None = None) -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    alt = load_json(STATE_FILE, {})
    if not force and alt.get("aktualisiert"):
        t = datetime.fromisoformat(alt["aktualisiert"].replace("Z", "+00:00"))
        if now_utc() - t < timedelta(minutes=110):
            return alt
    katalog = load_json(KATALOG_FILE, {})
    suchen = sorted({q for i in katalog["indikatoren"] for q in i.get("news", {}).get("suche", [])})
    items = fetch_news(suchen)
    if news_items:  # Meldungen aus bestehenden Server-Feeds: jedem Indikator per Muster zuordnen
        for it in news_items:
            for ind in katalog["indikatoren"]:
                nw = ind.get("news", {})
                if nw.get("suche"):
                    items.append(dict(it, suchbegriff=nw["suche"][0]))
    hist = alt.get("verlauf", [])
    inds = bewerte(katalog, items, hist)
    g = gesamt(inds, katalog)
    heute = datetime.now().strftime("%Y-%m-%d")
    hist = push_history(hist, {"datum": heute, "aufruestung": g["aufruestung"], "eskalation": g["eskalation"],
                               "kombi": g["kombi"], "stufe": g["stufe"],
                               "stufen": {i["id"]: i["stufe"] for i in inds},
                               "meldungen": {i["id"]: i["meldungen_7t"] for i in inds}})
    for i in inds:
        alt_st = None
        ziel = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        for h in hist:
            if h["datum"] <= ziel:
                alt_st = h["stufen"].get(i["id"])
        if alt_st is None and hist:
            alt_st = hist[0]["stufen"].get(i["id"])
        i["trend_30t"] = "→" if alt_st is None else "↑" if i["stufe"] > alt_st else "↓" if i["stufe"] < alt_st else "→"
    state = {
        "modul": "spannungsfall", "aktualisiert": iso(now_utc()), "katalog_bewertet_am": katalog.get("bewertet_am"),
        **g, "trend_7t": {"aufruestung": trend(hist, "aufruestung"), "eskalation": trend(hist, "eskalation")},
        "indikatoren": inds, "verlauf": hist, "ereignisse": _ereignisse(alt, inds, alt.get("ereignisse", [])),
        "veraltete_bewertungen": [i["id"] for i in inds if i["veraltet"]],
        "stufen_legende": katalog.get("stufen"), "kategorien_namen": {k: v["name"] for k, v in katalog["kategorien"].items()},
    }
    save_json(STATE_FILE, state)
    return state


def get_state() -> dict:
    s = load_json(STATE_FILE, {})
    return s or update(force=True)


# ------------------------------------------------------------------ Anbindung

def fruehwarnung_signale(state: dict | None = None) -> list[dict]:
    s = state or get_state()
    out = []
    if s.get("stufe", 1) >= 3:
        out.append({"bereich": "Spannungsfall DE", "titel": f"Gesamtstufe {s['stufe']}: {s['stufe_text']}",
                    "stufe": s["stufe"], "text": f"Eskalation {s['eskalation']}, Aufrüstung {s['aufruestung']} ({s['stufe_grund']})",
                    "quelle": "Indikatorenmodell"})
    for i in s.get("indikatoren", []):
        if i["anomalie"] or (i["stufe"] >= 3 and i["kategorie"] in ("bedrohung", "ausloeser") and i["stufe_aus"] == "Meldungen"):
            out.append({"bereich": "Spannungsfall DE", "titel": i["name"], "stufe": min(5, i["stufe"] + 1),
                        "text": f"{i['meldungen_7t']} Meldungen/7T" + (f" (Vorwochen-Mittel {i['vorwochen_mittel']})" if i["vorwochen_mittel"] is not None else ""),
                        "quelle": "Google News"})
        if i["pruefhinweis"]:
            out.append({"bereich": "Spannungsfall DE", "titel": "Prüfen: " + i["name"], "stufe": 3,
                        "text": i["pruefhinweis"], "quelle": "Google News"})
    return out


def heimat_beitrag(state: dict | None = None) -> dict:
    s = state or get_state()
    de = round(s.get("eskalation", 0) / 5)  # max 20
    return {"DE": min(20, de), "CH": min(10, de // 2)}


def lage_kontext(state: dict | None = None, max_zeichen: int = 1400) -> str:
    s = state or get_state()
    z = [f"SPANNUNGSFALL DE: Gesamtstufe {s.get('stufe')}/5 ({s.get('stufe_text')}). "
         f"Eskalation {s.get('eskalation')} {s.get('trend_7t',{}).get('eskalation','')}, "
         f"Aufrüstung {s.get('aufruestung')} {s.get('trend_7t',{}).get('aufruestung','')} (0-100)."]
    top = sorted(s.get("indikatoren", []), key=lambda i: (-i["stufe"], -i["meldungen_7t"]))[:7]
    for i in top:
        z.append(f"- {i['id']} {i['name']}: {i['stufe']}/4 {i.get('trend_30t','')} ({i['kriterium']}); "
                 f"{i['meldungen_7t']} Meld./7T" + (" ANOMALIE" if i["anomalie"] else ""))
        if i["beispiele"]:
            z.append(f"    · {i['beispiele'][0]['titel'][:110]}")
    neu = [e for e in s.get("ereignisse", []) if e["datum"] >= (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")]
    for e in neu[-4:]:
        z.append(f"! {e.get('text') or (e['name'] + ': Stufe ' + str(e['von']) + ' -> ' + str(e['nach']))}")
    z.append("Formelle Auslöser (Art. 80a/115a GG, NATO Art. 5): " +
             ", ".join(f"{i['id']}={'JA' if i['stufe'] >= 3 else 'nein'}" for i in s.get("indikatoren", []) if i["formell"]))
    return "\n".join(z)[:max_zeichen]


LAGE_ANWEISUNG = (
    "Zusätzliche Abschnitte der Lage: 'Energie' (Versorgung DE/CH, Gas, Strom, Ausfälle) und "
    "'Spannungsfall Deutschland' (Aufrüstung vs. akute Eskalation getrennt bewerten; Aufrüstung allein "
    "ist kein Kriegsindikator; formelle Auslöser nur nennen, wenn JA). Je 2-4 Sätze, nüchtern, mit Zahlen, "
    "keine Spekulation. Nur bei Veränderung oder Stufe >= 3 ausführlicher."
)


if __name__ == "__main__":
    import json
    st = update(force=True)
    print(lage_kontext(st))
    print(json.dumps({k: st[k] for k in ("aufruestung", "eskalation", "kombi", "stufe", "stufe_text")}, ensure_ascii=False))
