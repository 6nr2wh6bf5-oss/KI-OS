"""Modul ENERGIE: Energieengpaesse und Stromausfaelle (DE, CH, Europa).

Liefert einen Energie-Index 0-100, Stufe 1-5, Einzelindikatoren mit Stufe 0-4,
Verlauf (taeglich) und Signale fuer Fruehwarnung und Lage.

Quellen (alle kostenlos):
- energy-charts.info (Fraunhofer ISE, CC BY 4.0): Day-ahead-Preis DE-LU, Netzfrequenz
- Yahoo Finance: TTF-Gas (TTF=F), Brent (BZ=F)
- GIE AGSI+ (Gasspeicher DE/EU): kostenloser API-Key noetig (config: agsi_key)
- BFE opendata (Fuellungsgrad Speicherseen CH)
- Google News RSS: Meldungen zu Stromausfaellen, Sabotage an Energieanlagen

Aufruf durch den Server: energie.update() alle 30 Min. (Timer/Thread), energie.get_state() fuer /api/energie.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta, timezone

from wm_common import (STUFEN_TEXT, count_recent, match_any, norm, fetch_news, http_get, http_json,
                       index_zu_stufe, iso, load_json, now_utc, push_history, save_json,
                       stufe_aus_schwellen, trend)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("WM_DATA_DIR", os.path.join(BASE, "data"))
STATE_FILE = os.path.join(DATA_DIR, "energie_state.json")
MANUELL_FILE = os.path.join(BASE, "energie_manuell.json")
CONFIG_FILE = os.environ.get("WM_CONFIG", os.path.join(BASE, "config.json"))

# Naeherung typischer Fuellstand DE-Gasspeicher am Monatsersten (Mittel der Jahre vor 2022, gerundet).
# Nur Referenz fuer die Abweichung, keine gesetzliche Vorgabe (diese: § 35b EnWG, aktuelle Werte pruefen).
GAS_REF = {1: 78, 2: 62, 3: 45, 4: 35, 5: 40, 6: 52, 7: 63, 8: 73, 9: 82, 10: 89, 11: 93, 12: 88}

NEWS_DE = ["Stromausfall", "Blackout Stromnetz", "Netzstörung Strom", "Brandanschlag Stromnetz",
           "Gasmangel", "Strommangel", "Lastabwurf", "Stromausfall Schweiz", "OSTRAL Strom"]
NEWS_EN = ["power outage Europe", "blackout grid Europe", "gas shortage Europe"]

P_AUSFALL = ["stromausfall", "blackout", "netzstoerung", "ohne strom", "stromnetz ausgefallen",
             "power outage", "power cut", "blackout"]
P_GROSS = ["grossflaechig", "tausende haushalte", "zehntausende", "landesweit", "flaechendeckend",
           "mehrere tage", "katastrophenfall", "grossschadenslage", "nationwide", "millions without power",
           "hunderttausend"]
P_SABOTAGE = ["brandanschlag", "sabotage", "anschlag auf strom", "anschlag auf das stromnetz",
              "kabelschacht", "strommast", "umspannwerk", "pipeline beschaedigt", "seekabel",
              "attack on power grid", "sabotage pipeline"]
P_MANGEL = ["gasmangel", "strommangel", "lastabwurf", "rationierung", "kontingentierung", "ostral",
            "alarmstufe gas", "notfallstufe gas", "fruehwarnstufe gas", "netzreserve",
            "gas shortage", "rolling blackouts"]
P_AUSSCHLUSS = ["uebung", "probealarm", "film", "serie", "roman", "videospiel", "hoerspiel", "simulation"]

GEWICHTE = {
    "gas_de": 3, "gas_eu": 2, "ttf": 2, "brent": 1, "strompreis": 2, "frequenz": 2,
    "ausfall_de_ch": 3, "ausfall_europa": 1, "sabotage": 2, "mangel": 2, "gasstufe": 3, "speicher_ch": 2,
}


def _cfg() -> dict:
    return load_json(CONFIG_FILE, {})


def _ind(id_, name, stufe, wert, einheit, text, quelle, ok=True):
    return {"id": id_, "name": name, "stufe": int(stufe), "wert": wert, "einheit": einheit,
            "text": text, "quelle": quelle, "ok": ok}


def _fehler(id_, name, quelle, err):
    return {"id": id_, "name": name, "stufe": 0, "wert": None, "einheit": "", "ok": False,
            "text": f"keine Daten ({type(err).__name__})", "quelle": quelle}


# ------------------------------------------------------------------ Einzelindikatoren

def ind_gas(key: str) -> dict:
    land = "de" if key == "gas_de" else "eu"
    name = "Gasspeicher " + ("Deutschland" if land == "de" else "EU")
    quelle = "GIE AGSI+"
    k = _cfg().get("agsi_key")
    if not k:
        return {"id": key, "name": name, "stufe": 0, "wert": None, "einheit": "%", "ok": False,
                "text": "AGSI-Key fehlt (kostenlos: agsi.gie.eu, config.json: agsi_key)", "quelle": quelle}
    try:
        url = "https://agsi.gie.eu/api?" + ("country=de" if land == "de" else "type=eu") + "&size=10"
        j = http_json(url, headers={"x-key": k})
        row = j["data"][0]
        full = float(row["full"])
        tag = row.get("gasDayStart", "")
        d = datetime.strptime(tag, "%Y-%m-%d") if tag else now_utc()
        m, m2 = d.month, d.month % 12 + 1
        f = (d.day - 1) / 30.0
        ref = GAS_REF[m] * (1 - f) + GAS_REF[m2] * f
        defizit = ref - full
        st = stufe_aus_schwellen(defizit, [5, 12, 20, 30])
        tr = row.get("trend")
        txt = f"{full:.1f} % am {tag}, Referenz ca. {ref:.0f} % (Abweichung {-defizit:+.1f} Pp)"
        if tr not in (None, ""):
            txt += f", Tagestrend {float(tr):+.2f} Pp"
        return _ind(key, name, st, round(full, 1), "%", txt, quelle)
    except Exception as e:  # noqa: BLE001
        return _fehler(key, name, quelle, e)


def _yahoo(symbol: str) -> float:
    j = http_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d")
    return float(j["chart"]["result"][0]["meta"]["regularMarketPrice"])


def ind_ttf() -> dict:
    try:
        v = _yahoo("TTF=F")
        return _ind("ttf", "Gaspreis TTF", stufe_aus_schwellen(v, [40, 60, 100, 180]), round(v, 1),
                    "EUR/MWh", f"{v:.1f} EUR/MWh (2021 vor Krise ca. 20, Spitze Aug. 2022 > 300)", "Yahoo Finance TTF=F")
    except Exception as e:  # noqa: BLE001
        return _fehler("ttf", "Gaspreis TTF", "Yahoo Finance", e)


def ind_brent() -> dict:
    try:
        v = _yahoo("BZ=F")
        return _ind("brent", "Ölpreis Brent", stufe_aus_schwellen(v, [90, 110, 130, 150]), round(v, 1),
                    "USD/bbl", f"{v:.1f} USD/Fass", "Yahoo Finance BZ=F")
    except Exception as e:  # noqa: BLE001
        return _fehler("brent", "Ölpreis Brent", "Yahoo Finance", e)


def _ec_series(j: dict, prefer: tuple[str, ...]) -> list[float]:
    for k in prefer:
        if isinstance(j.get(k), list):
            return [x for x in j[k] if isinstance(x, (int, float))]
    for k, v in j.items():
        if k != "unix_seconds" and isinstance(v, list) and v and isinstance(v[0], (int, float, type(None))):
            return [x for x in v if isinstance(x, (int, float))]
    return []


def ind_strompreis() -> dict:
    q = "energy-charts.info (Fraunhofer ISE)"
    try:
        j = http_json("https://api.energy-charts.info/price?bzn=DE-LU")
        p = _ec_series(j, ("price",))
        if not p:
            raise ValueError("leer")
        avg, mx = sum(p) / len(p), max(p)
        st = max(stufe_aus_schwellen(avg, [150, 250, 400, 600]), stufe_aus_schwellen(mx, [500, 1000, 2000, 3500]))
        return _ind("strompreis", "Strompreis Day-ahead DE", st, round(avg, 1), "EUR/MWh",
                    f"Mittel {avg:.0f}, Spitze {mx:.0f} EUR/MWh (Knappheitssignal bei Spitzen > 1000)", q)
    except Exception as e:  # noqa: BLE001
        return _fehler("strompreis", "Strompreis Day-ahead DE", q, e)


def ind_frequenz() -> dict:
    q = "energy-charts.info Netzfrequenz"
    try:
        j = http_json("https://api.energy-charts.info/frequency?region=DE")
        f = _ec_series(j, ("data", "frequency"))
        f = [x for x in f if 45 < x < 55][-3600:]
        if not f:
            raise ValueError("leer")
        dmax = max(abs(x - 50.0) for x in f)
        st = stufe_aus_schwellen(dmax, [0.1, 0.15, 0.2, 0.5])
        return _ind("frequenz", "Netzfrequenz Europa", st, round(dmax * 1000), "mHz",
                    f"max. Abweichung {dmax*1000:.0f} mHz (Normalband ±200 mHz; Lastabwurf ab 49,0 Hz)", q)
    except Exception as e:  # noqa: BLE001
        return _fehler("frequenz", "Netzfrequenz Europa", q, e)


def ind_speicher_ch() -> dict:
    q = "BFE opendata, Füllungsgrad Speicherseen"
    url = _cfg().get("bfe_speicherseen_csv",
                     "https://www.uvek-gis.admin.ch/BFE/ogd/17/ogd17_fuellungsgrad_speicherseen.csv")
    try:
        raw = http_get(url).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(raw), delimiter=";" if raw.count(";") > raw.count(",") else ","))
        if not rows:
            raise ValueError("leer")
        cols = rows[0].keys()
        c_dat = next(c for c in cols if "datum" in c.lower() or "date" in c.lower())
        c_ist = next(c for c in cols if "totalch" in c.lower() and "speicherinhalt" in c.lower() and "max" not in c.lower())
        c_max = next(c for c in cols if "totalch" in c.lower() and "max" in c.lower())

        def pct(r):
            return float(r[c_ist]) / float(r[c_max]) * 100

        last = rows[-1]
        d = datetime.strptime(last[c_dat][:10], "%Y-%m-%d")
        kw = d.isocalendar()[1]
        vgl = [pct(r) for r in rows[:-1]
               if datetime.strptime(r[c_dat][:10], "%Y-%m-%d").isocalendar()[1] == kw
               and d.year - 5 <= int(r[c_dat][:4]) < d.year]
        ist = pct(last)
        mittel = sum(vgl) / len(vgl) if vgl else ist
        defizit = mittel - ist
        st = stufe_aus_schwellen(defizit, [5, 10, 15, 25])
        return _ind("speicher_ch", "Speicherseen Schweiz", st, round(ist, 1), "%",
                    f"{ist:.1f} % ({last[c_dat][:10]}), Mittel 5 Jahre KW{kw}: {mittel:.1f} %", q)
    except Exception as e:  # noqa: BLE001
        return _fehler("speicher_ch", "Speicherseen Schweiz", q, e)


def ind_gasstufe() -> dict:
    """Manuell gefuehrt (energie_manuell.json), da kein maschinenlesbarer Status existiert.
    Notfallplan Gas DE: Fruehwarn-, Alarm-, Notfallstufe (EU-VO 2017/1938, Art. 11)."""
    m = load_json(MANUELL_FILE, {})
    g = m.get("gasstufe_de", {})
    stufe_txt = g.get("stufe", "unbekannt")
    st = {"keine": 0, "fruehwarnstufe": 1, "alarmstufe": 3, "notfallstufe": 4}.get(norm(stufe_txt), 0)
    return _ind("gasstufe", "Notfallplan Gas DE", st, stufe_txt, "",
                f"{stufe_txt} (Stand {g.get('stand','?')}; {g.get('hinweis','')})".strip(),
                "BMWE/BNetzA, manuell gepflegt", ok=stufe_txt != "unbekannt")


def ind_news(items: list[dict]) -> list[dict]:
    res = []
    n, t = count_recent(items, P_AUSFALL, 7, P_AUSSCHLUSS)
    t_de = [x for x in t if x.get("suchbegriff") not in NEWS_EN]
    gross = [x for x in t_de if match_any(x["titel"], P_GROSS)]
    st = max(stufe_aus_schwellen(len(t_de), [8, 15, 30, 60]), min(4, stufe_aus_schwellen(len(gross), [1, 3, 6, 10])))
    res.append(_ind("ausfall_de_ch", "Stromausfälle DE/CH (Meldungen 7 T.)", st, len(t_de), "Meldungen",
                    f"{len(t_de)} Meldungen, davon {len(gross)} grossflaechig", "Google News",
                    ) | {"beispiele": t_de[:5]})
    t_eu = [x for x in t if x.get("suchbegriff") in NEWS_EN]
    gross_eu = [x for x in t_eu if match_any(x["titel"], P_GROSS)]
    st = max(stufe_aus_schwellen(len(t_eu), [10, 20, 40, 80]), min(3, stufe_aus_schwellen(len(gross_eu), [1, 3, 6, 10])))
    res.append(_ind("ausfall_europa", "Stromausfälle Europa (Meldungen 7 T.)", st, len(t_eu), "Meldungen",
                    f"{len(t_eu)} Meldungen, davon {len(gross_eu)} grossflaechig", "Google News") | {"beispiele": t_eu[:5]})
    n, t = count_recent(items, P_SABOTAGE, 7, P_AUSSCHLUSS)
    res.append(_ind("sabotage", "Anschläge/Sabotage Energieanlagen", stufe_aus_schwellen(n, [2, 5, 10, 20]), n,
                    "Meldungen", f"{n} Meldungen in 7 Tagen", "Google News") | {"beispiele": t[:5]})
    n, t = count_recent(items, P_MANGEL, 7, P_AUSSCHLUSS)
    res.append(_ind("mangel", "Mangel/Rationierung (Meldungen)", stufe_aus_schwellen(n, [3, 8, 15, 30]), n,
                    "Meldungen", f"{n} Meldungen in 7 Tagen", "Google News") | {"beispiele": t[:5]})
    return res


# ------------------------------------------------------------------ Gesamt

def berechne_index(inds: list[dict]) -> float:
    ok = [i for i in inds if i["ok"]]
    if not ok:
        return 0.0
    w = sum(GEWICHTE.get(i["id"], 1) for i in ok)
    mittel = sum(GEWICHTE.get(i["id"], 1) * i["stufe"] for i in ok) / w / 4 * 100
    spitze = max(i["stufe"] for i in ok) * 25
    return round(0.6 * mittel + 0.4 * spitze, 1)


def update(force: bool = False, news_items: list[dict] | None = None) -> dict:
    """Alle Indikatoren neu laden. news_items: optional zusaetzliche Meldungen aus den
    bestehenden Feeds des Servers ({titel, zeit(iso), link, quelle})."""
    os.makedirs(DATA_DIR, exist_ok=True)
    state = load_json(STATE_FILE, {})
    if not force and state.get("aktualisiert"):
        alt = datetime.fromisoformat(state["aktualisiert"].replace("Z", "+00:00"))
        if now_utc() - alt < timedelta(minutes=25):
            return state
    items = fetch_news(NEWS_DE) + fetch_news(NEWS_EN, "en", "GB")
    if news_items:
        items += news_items
    inds = [ind_gas("gas_de"), ind_gas("gas_eu"), ind_ttf(), ind_brent(), ind_strompreis(),
            ind_frequenz(), ind_speicher_ch(), ind_gasstufe()] + ind_news(items)
    idx = berechne_index(inds)
    hist = state.get("verlauf", [])
    heute = datetime.now().strftime("%Y-%m-%d")
    hist = push_history(hist, {"datum": heute, "index": idx,
                               **{i["id"]: i["stufe"] for i in inds if i["ok"]}})
    for i in inds:
        i["trend"] = "→"
        if i["ok"] and len(hist) >= 2:
            alt = next((h.get(i["id"]) for h in reversed(hist[:-1])
                        if h["datum"] <= (now_utc() - timedelta(days=7)).strftime("%Y-%m-%d")), hist[0].get(i["id"]))
            if alt is not None:
                i["trend"] = "↑" if i["stufe"] > alt else "↓" if i["stufe"] < alt else "→"
    stufe = index_zu_stufe(idx)
    state = {
        "modul": "energie", "aktualisiert": iso(now_utc()), "index": idx, "stufe": stufe,
        "stufe_text": STUFEN_TEXT[stufe], "trend_7d": trend(hist, "index"),
        "indikatoren": inds, "verlauf": hist,
        "datenluecken": [i["name"] for i in inds if not i["ok"]],
    }
    save_json(STATE_FILE, state)
    return state


def get_state() -> dict:
    s = load_json(STATE_FILE, {})
    return s or update(force=True)


# ------------------------------------------------------------------ Anbindung

def fruehwarnung_signale(state: dict | None = None) -> list[dict]:
    """Eintraege für das Fruehwarn-Panel: Indikatoren ab Stufe 3 oder Anstieg auf >= 2."""
    s = state or get_state()
    out = []
    for i in s.get("indikatoren", []):
        if i["ok"] and (i["stufe"] >= 3 or (i["stufe"] >= 2 and i.get("trend") == "↑")):
            out.append({"bereich": "Energie", "titel": i["name"], "stufe": min(5, i["stufe"] + 1),
                        "text": i["text"], "quelle": i["quelle"]})
    return out


def heimat_beitrag(state: dict | None = None) -> dict:
    """Punkte (0-20) für die HEIMATSCHUTZ-Ampeln DE und CH."""
    s = state or get_state()
    st = {i["id"]: i["stufe"] for i in s.get("indikatoren", []) if i["ok"]}
    de = st.get("gas_de", 0) * 2 + st.get("gasstufe", 0) * 2 + st.get("ausfall_de_ch", 0) * 2 + st.get("sabotage", 0)
    ch = st.get("speicher_ch", 0) * 3 + st.get("ausfall_de_ch", 0) * 2 + st.get("strompreis", 0)
    return {"DE": min(20, de), "CH": min(20, ch)}


def lage_kontext(state: dict | None = None, max_zeichen: int = 1100) -> str:
    """Kompakter Textblock für den Lage-Prompt (Haiku)."""
    s = state or get_state()
    z = [f"ENERGIE-INDEX {s.get('index')} / Stufe {s.get('stufe')} ({s.get('stufe_text')}), Trend 7T {s.get('trend_7d')}"]
    for i in sorted(s.get("indikatoren", []), key=lambda x: -x["stufe"]):
        if i["ok"]:
            z.append(f"- {i['name']}: Stufe {i['stufe']}/4 {i.get('trend','')} | {i['text']}")
            for b in i.get("beispiele", [])[:2]:
                z.append(f"    · {b['titel'][:110]}")
    if s.get("datenluecken"):
        z.append("Datenluecken: " + ", ".join(s["datenluecken"]))
    return "\n".join(z)[:max_zeichen]


if __name__ == "__main__":
    import json
    st = update(force=True)
    print(json.dumps({k: v for k, v in st.items() if k != "verlauf"}, ensure_ascii=False, indent=1)[:4000])
