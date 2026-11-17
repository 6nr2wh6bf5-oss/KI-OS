"""Modul OSTFLANKE: Baltikum, Suwalki-Korridor, Kaliningrad, Belarus, Ostsee.

Ziel: jede gemeldete Bewegung/Verlegung und jeden Vorfall in der Region erfassen, mit
wer / was / wie viel / wann / wohin, Quelle, Zeit, Verlaesslichkeit und Status (bestaetigt/unbestaetigt).

Quellen (nur offen, siehe ostflanke_quellen.json):
1. Offizielle Stellen (Ministerien, Streitkraefte, Grenzschutz LT/LV/EE/PL/FI/SE, DE, UK, US, CA, FR, NL, NATO)
   per RSS oder Google-News-Suche mit site:-Filter. Eigenangaben RU/BY getrennt (Verlaesslichkeit B).
2. Fachmedien und Analysen (LRT, ERR, LSM, Defence24, ISW, OSW, ICDS, RUSI) und thematische Suchen.
3. Technische Rohsignale: Militaerflugzeuge ADS-B (api.adsb.lol/v2/mil), NOTAMs (ICAO-API, Schluessel noetig),
   AIS Ostsee (Einspeisung aus dem bestehenden aisstream-Modul ueber ais_einspeisen()).

Grenzen (immer mitkommunizieren): keine eingestuften Lagedaten. Russland/Belarus melden Verlegungen nicht
oder irrefuehrend; Kriegsschiffe und Kampfflugzeuge senden oft kein AIS/ADS-B. Die Felder werden nur
befuellt, wenn die Quelle sie hergibt (nichts geschaetzt).

Bewertung: 8 Indikatoren O1-O8 (Stufe 0-4) = max(manuelle Basis, Meldungsstufe, technische Stufe),
+1 bei Anomalie (>= 2x Vorwochen). Zwei Teilindizes 0-100: ESKALATION (O1, O2, O4-O8) und
VERLEGUNG NATO (O3, nur Anzeige, Abschreckung ist kein Eskalationsindikator). Gesamtstufe 1-5 aus Eskalation.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import urllib.parse
from datetime import datetime, timedelta

from wm_common import (fetch_news, http_get, http_json, iso, load_json, now_utc, parse_rss,
                       push_history, save_json, trend)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("WM_DATA_DIR", os.path.join(BASE, "data"))
CONFIG_FILE = os.environ.get("WM_CONFIG", os.path.join(BASE, "config.json"))
STATE_FILE = os.path.join(DATA_DIR, "ostflanke_state.json")
KATALOG_FILE = os.path.join(BASE, "ostflanke_quellen.json")

GESAMT_TEXT = {
    1: "Ruhig",
    2: "Erhoehte Spannung (hybride Vorfaelle, Uebungen)",
    3: "Angespannt (gehaeufte Vorfaelle, grenznahe Konzentration)",
    4: "Kritisch (bestaetigter Aufmarsch oder formelle Schritte)",
    5: "Akut (bewaffneter Konflikt / Bündnisfall)",
}
INTERVALL_MIN = 55          # News-Lauf hoechstens stuendlich
ADSB_INTERVALL_MIN = 9      # ADS-B alle 10 Min.
NOTAM_INTERVALL_H = 12      # ICAO-Kontingent schonen
GEWICHT_VERL = {"A": 1.0, "B": 0.7, "C": 0.35}
SPRACHE = {"en": ("en-US", "US"), "de": ("de", "DE"), "pl": ("pl", "PL"), "lt": ("lt", "LT"),
           "ru": ("ru", "RU"), "fr": ("fr", "FR"), "nl": ("nl", "NL")}

AKTEURE = {
    "RU": ["russia", "russian", "russland", "russisch", "rosja", "rosyjsk", "rusij", "krievij", "venemaa", "kremlin", "kreml",
           "baltic fleet", "baltische flotte", "moscow", "moskau", "putin"],
    "BY": ["belarus", "belarusian", "weissruss", "bialorus", "baltarus", "baltkriev", "valgevene", "lukashenk", "lukaschenk", "minsk"],
    "DE": ["bundeswehr", "german", "germany", "deutsch", "brigade litauen", "panzerbrigade 45", "45th armoured", "pistorius", "niemieck", "vokiet"],
    "UK": ["british", "britain", "united kingdom", "royal navy", "royal air force", " raf ", "uk ", "britisch", "grossbritannien", "joint expeditionary force", "cabrit"],
    "US": ["u.s.", "us army", "us troops", "american", "amerikan", "pentagon", "united states", "eucom", "v corps", "usaf"],
    "CA": ["canada", "canadian", "kanad", "operation reassurance"],
    "FR": ["france", "french", "frankreich", "franzoes", "mission lynx"],
    "NL": ["netherlands", "dutch", "niederlaend", "niederlande"],
    "NO": ["norway", "norwegian", "norweg"],
    "SE": ["sweden", "swedish", "schwed"],
    "FI": ["finland", "finnish", "finnland", "finnisch"],
    "DK": ["denmark", "danish", "daenemark", "daenisch"],
    "PL": ["poland", "polish", "polen", "polnisch", "wojsko polskie", "polsk"],
    "LT": ["lithuania", "lithuanian", "litauen", "litauisch", "lietuv", "litwa", "litewsk"],
    "LV": ["latvia", "latvian", "lettland", "lettisch", "latvij", "lotwa", "lotewsk"],
    "EE": ["estonia", "estonian", "estland", "estnisch", "eesti"],
    "NATO": ["nato", "shape", "allied air command", "air policing", "efp", "forward land forces", "baltic sentry", "eastern sentry"],
}
WAS = [
    ("Panzer/Kampffahrzeuge", ["tank", "armour", "armor", "leopard", "abrams", "t-72", "t-80", "t-90", "panzer", "czolg", "ifv", "infantry fighting"]),
    ("Artillerie/Raketen", ["artillery", "artillerie", "himars", "iskander", "missile", "rakete", "oreshnik", "k9", "krab", "mlrs", "kalibr"]),
    ("Luftabwehr", ["air defen", "luftabwehr", "patriot", "iris-t", "nasams", "s-400", "s-300", "pantsir"]),
    ("Kampfflugzeuge", ["fighter", "kampfjet", "f-35", "f-16", "eurofighter", "typhoon", "rafale", "gripen", "su-27", "su-30", "su-35", "mig-31", "bomber"]),
    ("Drohnen", ["drone", "drohne", "uav", "shahed", "geran", "gerbera", "dron"]),
    ("Ballone", ["balloon", "ballon", "balion"]),
    ("Marine/Schiffe", ["warship", "frigate", "corvette", "submarine", "kriegsschiff", "fregatte", "korvette", "u-boot", "landing ship", "navy", "naval", "marine"]),
    ("Kabel/Pipeline", ["cable", "kabel", "pipeline", "anchor", "anker"]),
    ("Schattenflotte", ["shadow fleet", "schattenflotte"]),
    ("GNSS-Stoerung", ["gps", "gnss", "jamming", "spoofing", "stoersender"]),
    ("Nuklear", ["nuclear", "nuklear", "atomwaff", "atomic"]),
    ("Uebung", ["exercise", "drill", "uebung", "manoever", "maneuver", "zapad", "cwiczen", "pratyb", "baltops", "freedom shield"]),
    ("Verlegung", ["deploy", "redeploy", "relocat", "transfer", "reinforce", "arrive", "verleg", "verstaerk", "eintreff", "rotation", "move"]),
    ("Truppen", ["troops", "soldier", "personnel", "battalion", "brigade", "division", "regiment", "truppe", "soldat", "bataillon", "zolnierz", "kariai"]),
    ("Grenze", ["border", "grenze", "granic", "sienos", "frontier", "crossing", "grenzuebergang"]),
    ("Luftraum", ["airspace", "luftraum", "air alert", "luftalarm", "scramble", "intercept", "alarmstart"]),
    ("Mobilmachung/Formell", ["mobiliz", "mobilis", "mobilmach", "article 4", "artikel 4", "article 5", "artikel 5", "martial law", "state of emergency", "ausnahmezustand"]),
]
EINHEITEN = {
    "soldiers": "Soldaten", "soldier": "Soldaten", "troops": "Soldaten", "personnel": "Soldaten", "servicemen": "Soldaten",
    "soldaten": "Soldaten", "zolnierzy": "Soldaten", "kariu": "Soldaten",
    "tanks": "Panzer", "panzer": "Panzer", "kampfpanzer": "Panzer", "vehicles": "Fahrzeuge", "fahrzeuge": "Fahrzeuge",
    "aircraft": "Flugzeuge", "jets": "Flugzeuge", "flugzeuge": "Flugzeuge", "kampfjets": "Flugzeuge", "fighters": "Flugzeuge",
    "helicopters": "Hubschrauber", "hubschrauber": "Hubschrauber",
    "ships": "Schiffe", "warships": "Schiffe", "vessels": "Schiffe", "schiffe": "Schiffe", "kriegsschiffe": "Schiffe",
    "drones": "Drohnen", "drohnen": "Drohnen", "balloons": "Ballone", "ballone": "Ballone",
    "launchers": "Werfer", "systems": "Systeme", "systeme": "Systeme",
    "battalions": "Bataillone", "bataillone": "Bataillone", "brigades": "Brigaden", "brigaden": "Brigaden",
    "divisions": "Divisionen", "divisionen": "Divisionen",
}
_ZAHLWORT = {"thousand": 1000, "thousands": 1000, "tausend": 1000, "tausende": 1000, "tausenden": 1000,
             "hundreds": 100, "hunderte": 100, "dozens": 12, "dutzende": 12,
             "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "zwei": 2, "drei": 3, "vier": 4, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10}
_RE_MENGE = re.compile(
    r"(?<![\w.-])(\d{1,3}(?:[.,' ]\d{3})+|\d+(?:[.,]\d+)?|" + "|".join(sorted(_ZAHLWORT, key=len, reverse=True)) + r")"
    r"(?:\s*(thousand|tausend|k|000))?\s+(?:[a-z0-9-]+\s+){0,2}?(?:[a-z0-9]+-)?(" + "|".join(sorted(EINHEITEN, key=len, reverse=True)) + r")\b")
_MONATE = ("january|february|march|april|may|june|july|august|september|october|november|december|"
           "januar|februar|maerz|mai|juni|juli|oktober|dezember")
_RE_DATUM = re.compile(r"\b(\d{1,2}\.?\s+(?:" + _MONATE + r")|(?:" + _MONATE + r")\s+\d{1,2})\b")


# ---------------------------------------------------------------- Textwerkzeuge

def norm(s: str) -> str:
    s = (s or "").lower().replace("ł", "l").replace("ß", "ss")
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " " + re.sub(r"\s+", " ", s) + " "


def _hat(t: str, muster: list[str]) -> bool:
    return any(m in t for m in muster)


def _cfg() -> dict:
    return load_json(CONFIG_FILE, {})


def _parse_zeit(z: str | None) -> datetime | None:
    if not z:
        return None
    try:
        return datetime.fromisoformat(z.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------- Felder wer/was/wie viel/wann/wohin

def akteure(t: str) -> list[str]:
    return [k for k, m in AKTEURE.items() if _hat(t, m)]


def was(t: str) -> list[str]:
    return [name for name, m in WAS if _hat(t, m)]


def wie_viel(t: str) -> list[str]:
    out = []
    for m in _RE_MENGE.finditer(t):
        roh, mult, einheit = m.group(1), m.group(2), m.group(3)
        if roh in _ZAHLWORT:
            if _ZAHLWORT[roh] in (1000, 100, 12):
                wort = {1000: "Tausende", 100: "Hunderte", 12: "Dutzende"}[_ZAHLWORT[roh]]
                out.append(f"{wort} {EINHEITEN[einheit]}")
                continue
            n = float(_ZAHLWORT[roh])
        else:
            try:
                n = float(re.sub(r"[.,' ](?=\d{3}\b)", "", roh).replace(",", "."))
            except ValueError:
                continue
        if mult in ("thousand", "tausend", "k", "000"):
            n *= 1000
        if n <= 0 or n > 2_000_000 or (re.fullmatch(r"(19|20)\d\d", roh) and not mult):
            continue
        out.append(f"{int(n):,}".replace(",", "'") + f" {EINHEITEN[einheit]}")
    return list(dict.fromkeys(out))[:3]


def wann(t: str, pub: str | None) -> dict:
    return {"gemeldet": pub, "zeitangaben": list(dict.fromkeys(m.group(1).strip() for m in _RE_DATUM.finditer(t)))[:2]}


def wohin(t: str, orte: list[dict]) -> list[dict]:
    treffer = [o for o in orte if _hat(t, o["muster"])]
    # spezifische Orte vor Laendern/Meeren
    rang = {"korridor": 0, "ru": 1, "by": 1, "nato": 1, "see": 2, "land": 3}
    treffer.sort(key=lambda o: (rang.get(o["art"], 2), o["art"] == "by" and o["id"] == "belarus"))
    return [{"id": o["id"], "name": o["name"], "lat": o["lat"], "lon": o["lon"], "art": o["art"]} for o in treffer[:3]]


def verlaesslichkeit(item: dict, quelle: dict | None, kat: dict) -> str:
    if quelle and quelle.get("typ") in ("offiziell", "gegenseite"):
        return quelle.get("verl", "B")
    pub = norm(item.get("quelle", "") + " " + item.get("link", ""))
    if _hat(pub, kat.get("verlaessliche_verlage", [])):
        return "B"
    return quelle.get("verl", "C") if quelle else "C"


def relevant(t: str, quelle: dict | None, kat: dict) -> bool:
    mil = _hat(t, kat["militaer_muster"])
    if quelle and not quelle.get("region", True):
        return mil
    return mil and (_hat(t, kat["region_muster"]) or any(_hat(t, o["muster"]) for o in kat["orte"]))


def meldung_aus_item(it: dict, quelle: dict | None, kat: dict) -> dict:
    t = norm(it.get("titel", ""))
    wer = akteure(t)
    q_land = (quelle or {}).get("land")
    if quelle and quelle.get("typ") == "offiziell" and q_land and q_land not in wer:
        wer = wer + [q_land] if not wer else wer
    v = verlaesslichkeit(it, quelle, kat)
    return {
        "titel": it.get("titel", ""), "link": it.get("link", ""),
        "quelle": (quelle or {}).get("name") or it.get("quelle") or "Google News",
        "verlag": it.get("quelle", ""), "quelle_id": (quelle or {}).get("id", "thema"),
        "quelle_typ": (quelle or {}).get("typ", "medien"),
        "zeit": it.get("zeit"), "verl": v,
        "eigenangabe": (quelle or {}).get("typ") == "gegenseite",
        "wer": wer, "was": was(t), "wie_viel": wie_viel(t), "wann": wann(t, it.get("zeit")), "wohin": wohin(t, kat["orte"]),
    }


# ---------------------------------------------------------------- Abruf

def _gnews(query: str, lang: str) -> list[dict]:
    hl, gl = SPRACHE.get(lang, ("en-US", "US"))
    return fetch_news([query], lang=hl, country=gl, pause=1.0)


def sammeln(kat: dict, diagnose: dict) -> list[dict]:
    """Alle Quellen abrufen -> relevante Meldungen (mit Feldern)."""
    meldungen = []
    for q in kat["quellen"]:
        items, weg = [], None
        if q.get("rss"):
            try:
                items = parse_rss(http_get(q["rss"], timeout=20))
                weg = "rss"
            except Exception as e:  # noqa: BLE001
                diagnose[q["id"]] = f"RSS-Fehler: {type(e).__name__}"
        if not items and q.get("gnews"):
            items = _gnews(q["gnews"], q.get("lang", "en"))
            weg = "gnews"
        diagnose[q["id"]] = diagnose.get(q["id"], "") + f" {weg or 'keine Daten'}: {len(items)}"
        for it in items:
            t = norm(it["titel"])
            if relevant(t, q, kat):
                meldungen.append(meldung_aus_item(it, q, kat))
    for lang, suchen in kat.get("suchen_thematisch", {}).items():
        for s in suchen:
            items = _gnews(s, lang)
            diagnose[f"thema:{s[:30]}"] = len(items)
            for it in items:
                t = norm(it["titel"])
                if relevant(t, None, kat):
                    meldungen.append(meldung_aus_item(it, None, kat))
    return meldungen


# ---------------------------------------------------------------- Buendeln und bestaetigen

def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", norm(s))}


def buendeln(meldungen: list[dict], tage: int = 14) -> list[dict]:
    """Gleiche Ereignisse (aehnlicher Titel, gleicher Ort, +-36 h) zusammenfassen.
    Status: bestaetigt (offiziell A), bestaetigt (>= 2 unabhaengige Verlage), Eigenangabe RU/BY, unbestaetigt."""
    grenze = now_utc() - timedelta(days=tage)
    ms = [m for m in meldungen if (_parse_zeit(m["zeit"]) or now_utc()) >= grenze]
    ms.sort(key=lambda m: m["zeit"] or "", reverse=True)
    ereignisse: list[dict] = []
    for m in ms:
        tok = _tokens(m["titel"])
        ort = m["wohin"][0]["id"] if m["wohin"] else None
        zm = _parse_zeit(m["zeit"]) or now_utc()
        ziel = None
        for e in ereignisse:
            ze = _parse_zeit(e["zeit"]) or now_utc()
            if abs((ze - zm).total_seconds()) > 36 * 3600:
                continue
            jac = len(tok & e["_tok"]) / max(1, len(tok | e["_tok"]))
            orte_m = {w["id"] for w in m["wohin"] if w["art"] not in ("land", "see")}
            gleiche_menge = bool(set(m["wie_viel"]) & set(e["wie_viel"]))
            gleicher_akteur = bool(set(m["wer"]) & set(e["wer"]))
            gleicher_ort = bool(orte_m & e["_orte"])
            gleiches_land = bool({w["id"] for w in m["wohin"]} & e["_alle_orte"])
            if jac >= 0.45 or (jac >= 0.2 and gleicher_ort) or (jac >= 0.3 and gleiches_land and gleicher_akteur) or (gleiche_menge and gleicher_akteur and (gleicher_ort or jac >= 0.15)):
                ziel = e
                break
        if ziel is None:
            ziel = dict(m, quellen=[], _tok=set(tok), _ort=ort,
                        _orte={w["id"] for w in m["wohin"] if w["art"] not in ("land", "see")},
                        _alle_orte={w["id"] for w in m["wohin"]})
            ereignisse.append(ziel)
        else:
            ziel["_tok"] |= tok
            ziel["_alle_orte"] |= {w["id"] for w in m["wohin"]}
            ziel["_orte"] |= {w["id"] for w in m["wohin"] if w["art"] not in ("land", "see")}
            for f in ("wer", "was", "wie_viel"):
                ziel[f] = list(dict.fromkeys(ziel[f] + m[f]))
            if not ziel["wohin"] and m["wohin"]:
                ziel["wohin"] = m["wohin"]
            if "ABC".index(m["verl"]) < "ABC".index(ziel["verl"]):
                ziel.update({k: m[k] for k in ("titel", "link", "quelle", "verl", "quelle_typ", "eigenangabe")})
        if not any(q["link"] == m["link"] for q in ziel["quellen"]):
            ziel["quellen"].append({"name": m["quelle"], "verlag": m["verlag"], "link": m["link"], "verl": m["verl"],
                                    "typ": m["quelle_typ"]})
    out = []
    for e in ereignisse:
        verlage = {norm(q["verlag"] or q["name"]).strip() for q in e["quellen"]}
        offiziell = any(q["verl"] == "A" and q["typ"] == "offiziell" for q in e["quellen"])
        if offiziell:
            status = "bestätigt (offiziell)"
        elif len(verlage) >= 2 and any(q["verl"] in ("A", "B") for q in e["quellen"]):
            status = "bestätigt (mehrere Quellen)"
        elif e["eigenangabe"]:
            status = "Eigenangabe RU/BY"
        elif e["verl"] == "B":
            status = "unbestätigt (1 seriöse Quelle)"
        else:
            status = "unbestätigt"
        e["status"] = status
        e["n_quellen"] = len(e["quellen"])
        e["gewicht"] = GEWICHT_VERL[e["verl"]] * (1.2 if status.startswith("bestätigt") else 1.0)
        e["id"] = "e" + hashlib.md5((e["titel"][:60] + (e["zeit"] or "")[:10]).encode("utf-8")).hexdigest()[:10]
        e.pop("_tok", None)
        e.pop("_ort", None)
        e.pop("_orte", None)
        e.pop("_alle_orte", None)
        e["quellen"] = e["quellen"][:5]
        out.append(e)
    return out


# ---------------------------------------------------------------- Technische Signale

def _typ_klasse(t: str, kat: dict) -> str:
    t = (t or "").upper()
    for k, typen in kat["flugzeugtypen"].items():
        if any(t.startswith(x) for x in typen):
            return k
    return "sonstige"


def adsb_lauf(kat: dict, tech: dict) -> None:
    """Militaerflugzeuge mit Transponder in der Region (adsb.lol, frei, ohne Schluessel)."""
    b = kat["bbox"]
    try:
        j = http_json("https://api.adsb.lol/v2/mil", timeout=25)
    except Exception as e:  # noqa: BLE001
        tech["adsb_fehler"] = f"{type(e).__name__}"
        return
    jetzt = []
    for a in j.get("ac", []) or []:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None or not (b["sued"] <= lat <= b["nord"] and b["west"] <= lon <= b["ost"]):
            continue
        jetzt.append({"hex": a.get("hex"), "cs": (a.get("flight") or "").strip(), "typ": a.get("t") or "",
                      "reg": a.get("r") or "", "klasse": _typ_klasse(a.get("t"), kat),
                      "lat": round(lat, 2), "lon": round(lon, 2), "alt": a.get("alt_baro")})
    heute = datetime.now().strftime("%Y-%m-%d")
    tag = tech.setdefault("adsb_tage", {}).setdefault(heute, {"hex": [], "max_gleichzeitig": 0, "klassen": {}})
    for f in jetzt:
        if f["hex"] and f["hex"] not in tag["hex"]:
            tag["hex"].append(f["hex"])
            tag["klassen"][f["klasse"]] = tag["klassen"].get(f["klasse"], 0) + 1
    tag["max_gleichzeitig"] = max(tag["max_gleichzeitig"], len(jetzt))
    tech["adsb_jetzt"] = jetzt
    tech["adsb_zeit"] = iso(now_utc())
    tech.pop("adsb_fehler", None)
    for d in sorted(tech["adsb_tage"])[:-30]:
        del tech["adsb_tage"][d]


def adsb_bewertung(tech: dict) -> dict:
    tage = tech.get("adsb_tage", {})
    heute = datetime.now().strftime("%Y-%m-%d")
    t = tage.get(heute)
    if not t:
        return {"stufe": 0, "text": "keine ADS-B-Daten", "ok": False}
    vor = [len(v["hex"]) for d, v in sorted(tage.items()) if d < heute][-14:]
    mittel = sum(vor) / len(vor) if len(vor) >= 3 else None
    n = len(t["hex"])
    sonder = sum(t["klassen"].get(k, 0) for k in ("tanker", "awacs", "aufklaerung"))
    stufe = 0
    if mittel:
        r = n / max(1.0, mittel)
        stufe = 1 if r >= 1.3 else 0
        stufe = 2 if r >= 2 and n >= 8 else stufe
        stufe = 3 if r >= 3 and n >= 15 else stufe
    if t["max_gleichzeitig"] >= 12:   # Schwelle wie Upstream-Theater "baltic" critical
        stufe = max(stufe, 3)
    elif t["max_gleichzeitig"] >= 5:
        stufe = max(stufe, 1)
    txt = (f"heute {n} Militaerflugzeuge (max. {t['max_gleichzeitig']} gleichzeitig), davon Tanker/AWACS/Aufklaerer {sonder}"
           + (f"; Mittel Vortage {mittel:.1f}" if mittel else "; Vergleichswerte ab Tag 4"))
    return {"stufe": stufe, "text": txt, "ok": True, "anzahl": n, "mittel": round(mittel, 1) if mittel else None,
            "klassen": t["klassen"], "anomalie": bool(mittel and n >= 2 * mittel and n >= 8)}


_NOTAM_MUSTER = re.compile(r"\b(DANGER AREA|RESTRICTED AREA|PROHIBITED AREA|AIRSPACE CLOSED|AD CLSD|TEMPO RESERVED|"
                           r"TSA|TRA|MIL(ITARY)? (EXER|ACT)|MISSILE|ROCKET|GUN ?FIRING|UAS|UAV|DRONE|GNSS|GPS|JAMMING|INTERFERENCE)\b")


def notam_lauf(kat: dict, tech: dict) -> None:
    key = _cfg().get("icao_api_key")
    if not key:
        tech["notam_fehler"] = "kein icao_api_key in config.json (Datenluecke)"
        return
    letzte = _parse_zeit(tech.get("notam_zeit"))
    if letzte and now_utc() - letzte < timedelta(hours=_cfg().get("ostflanke", {}).get("notam_intervall_h", NOTAM_INTERVALL_H)):
        return
    url = ("https://dataservices.icao.int/api/notams-realtime-list?api_key=" + urllib.parse.quote(key)
           + "&format=json&locations=" + ",".join(kat["notam_orte"]))
    try:
        daten = http_json(url, timeout=30)
    except Exception as e:  # noqa: BLE001
        tech["notam_fehler"] = f"{type(e).__name__}"
        return
    out = []
    for n in daten if isinstance(daten, list) else []:
        txt = (n.get("iteme") or n.get("all") or "").upper()
        m = _NOTAM_MUSTER.search(txt)
        if not m:
            continue
        out.append({"ort": n.get("itema") or n.get("location"), "id": n.get("id") or n.get("key"),
                    "art": "GNSS" if re.search(r"GNSS|GPS|JAMMING|INTERFERENCE", txt) else "Sperrgebiet/Aktivität",
                    "text": txt[:220], "bis": n.get("enddate") or n.get("endvalidity")})
    tech["notams"] = out
    tech["notam_zeit"] = iso(now_utc())
    heute = datetime.now().strftime("%Y-%m-%d")
    tech.setdefault("notam_tage", {})[heute] = len(out)
    tech.pop("notam_fehler", None)


def notam_bewertung(tech: dict) -> dict:
    if "notams" not in tech:
        return {"stufe": 0, "ok": False, "text": tech.get("notam_fehler", "keine NOTAM-Daten")}
    tage = tech.get("notam_tage", {})
    werte = [v for _, v in sorted(tage.items())][:-1][-14:]
    n = len(tech["notams"])
    mittel = sum(werte) / len(werte) if len(werte) >= 3 else None
    stufe = 0
    if mittel is not None:
        stufe = 1 if n >= 1.5 * mittel and n >= 3 else 0
        stufe = 2 if n >= 2 * mittel and n >= 6 else stufe
    if any("AIRSPACE CLOSED" in x["text"] or "AD CLSD" in x["text"] for x in tech["notams"]):
        stufe = max(stufe, 3)
    return {"stufe": stufe, "ok": True, "anzahl": n, "mittel": round(mittel, 1) if mittel is not None else None,
            "text": f"{n} relevante NOTAMs (Sperrgebiete/GNSS)" + (f", Mittel {mittel:.1f}" if mittel is not None else "")}


def ais_einspeisen(schiffe: list[dict]) -> dict:
    """Vom bestehenden aisstream-Modul aufrufen: schiffe = [{mmsi, name, typ(AIS-Schiffstyp int), lat, lon}].
    Zaehlt Militaer (35), Behoerden (55) und russische Flagge (MMSI 273...) in der Region."""
    kat = load_json(KATALOG_FILE, {})
    b = kat.get("bbox", {"sued": 52, "nord": 61, "west": 13, "ost": 33})
    st = load_json(STATE_FILE, {})
    tech = st.setdefault("technik", {})
    mil, beh, ru = [], 0, 0
    for s in schiffe or []:
        lat, lon = s.get("lat"), s.get("lon")
        if lat is None or lon is None or not (b["sued"] <= lat <= b["nord"] and b["west"] <= lon <= b["ost"]):
            continue
        mmsi = str(s.get("mmsi", ""))
        if s.get("typ") == 35:
            mil.append({"name": s.get("name", ""), "mmsi": mmsi, "lat": round(lat, 2), "lon": round(lon, 2), "ru": mmsi.startswith("273")})
        if s.get("typ") == 55:
            beh += 1
        if mmsi.startswith("273"):
            ru += 1
    heute = datetime.now().strftime("%Y-%m-%d")
    tag = tech.setdefault("ais_tage", {}).setdefault(heute, {"mil_max": 0, "ru_max": 0})
    tag["mil_max"] = max(tag["mil_max"], len(mil))
    tag["ru_max"] = max(tag["ru_max"], ru)
    for d in sorted(tech["ais_tage"])[:-30]:
        del tech["ais_tage"][d]
    tech["ais_jetzt"] = {"militaer": mil[:40], "behoerden": beh, "russische_flagge": ru, "zeit": iso(now_utc())}
    save_json(STATE_FILE, st)
    return tech["ais_jetzt"]


def ais_bewertung(tech: dict) -> dict:
    tage = tech.get("ais_tage", {})
    heute = datetime.now().strftime("%Y-%m-%d")
    if heute not in tage:
        return {"stufe": 0, "ok": False, "text": "keine AIS-Einspeisung (aisstream anbinden)"}
    vor = [v["mil_max"] for d, v in sorted(tage.items()) if d < heute][-14:]
    n = tage[heute]["mil_max"]
    mittel = sum(vor) / len(vor) if len(vor) >= 3 else None
    stufe = 0
    if mittel is not None:
        stufe = 1 if n >= 1.5 * mittel and n >= 4 else 0
        stufe = 2 if n >= 2 * mittel and n >= 8 else stufe
    return {"stufe": stufe, "ok": True, "anzahl": n, "mittel": round(mittel, 1) if mittel is not None else None,
            "text": f"max. {n} Militaerschiffe mit AIS (Kriegsschiffe oft ohne AIS)" + (f", Mittel {mittel:.1f}" if mittel is not None else "")}


# ---------------------------------------------------------------- Bewertung

def _stufe(n: float, schwellen: list[float]) -> int:
    s = 0
    for i, g in enumerate(schwellen, start=1):
        if n >= g:
            s = i
    return s


def _vorwochen(hist: list[dict], key: str) -> float | None:
    werte = []
    for w in (7, 14, 21, 28):
        ziel = (datetime.now() - timedelta(days=w)).strftime("%Y-%m-%d")
        k = [h for h in hist if h["datum"] <= ziel and key in h.get("meldungen", {})]
        if k:
            werte.append(k[-1]["meldungen"][key])
    return sum(werte) / len(werte) if len(werte) >= 2 else None


def bewerte(kat: dict, ereignisse: list[dict], tech_b: dict, hist: list[dict]) -> list[dict]:
    grenze = now_utc() - timedelta(days=7)
    res = []
    for ind in kat["indikatoren"]:
        treffer = []
        for e in ereignisse:
            if (_parse_zeit(e["zeit"]) or now_utc()) < grenze:
                continue
            t = norm(e["titel"])
            if not _hat(t, ind["muster"]) or _hat(t, ind.get("ausschluss", [])):
                continue
            if ind.get("akteure") and not set(ind["akteure"]) & set(e["wer"]):
                continue
            treffer.append(e)
        # je Quelle hoechstens 3 Ereignisse pro Indikator (eine fleissige Behoerde soll den Wert nicht allein treiben)
        je_quelle: dict = {}
        gezaehlt = []
        for e in treffer:
            je_quelle[e["quelle_id"]] = je_quelle.get(e["quelle_id"], 0) + 1
            if je_quelle[e["quelle_id"]] <= 3:
                gezaehlt.append(e)
        n_gew = round(sum(e["gewicht"] for e in gezaehlt), 1)
        ns = _stufe(n_gew, ind["schwellen"])
        mittel = _vorwochen(hist, ind["id"])
        anomalie = bool(mittel and n_gew >= max(2, ind["schwellen"][0]) and n_gew >= 2 * mittel)
        if anomalie:
            ns = min(4, ns + 1)
        ts, ttxt = 0, ""
        if ind["id"] == "O6":
            ts = max(tech_b["adsb"]["stufe"], tech_b["notam"]["stufe"])
            ttxt = "; ".join(x["text"] for x in (tech_b["adsb"], tech_b["notam"]) if x.get("ok"))
        if ind["id"] == "O5":
            ts, ttxt = tech_b["ais"]["stufe"], tech_b["ais"]["text"] if tech_b["ais"].get("ok") else ""
        basis = ind["basis"]
        formell = ind.get("formell", False)
        if formell:
            eff, aus = basis["stufe"], "Basis (formell, nur manuell)"
        else:
            eff = max(basis["stufe"], ns, ts)
            aus = "Basis" if eff == basis["stufe"] and eff > max(ns, ts) else "Meldungen" if ns >= ts else "Technik"
        pruef = None
        if formell and treffer:
            pruef = f"{len(treffer)} Meldungen zu formellen Schritten (z.B. Art. 4) - Status manuell prüfen."
        res.append({
            "id": ind["id"], "name": ind["name"], "index": ind["index"], "gewicht": ind["gewicht"], "formell": formell,
            "stufe": eff, "basis_stufe": basis["stufe"], "news_stufe": ns, "technik_stufe": ts, "stufe_aus": aus,
            "kriterium": ind["kriterien"][eff], "basis_text": basis["text"], "basis_quelle": basis.get("quelle", ""),
            "stand": basis.get("stand"), "meldungen_7t": len(treffer), "gewichtet_7t": n_gew,
            "vorwochen_mittel": round(mittel, 1) if mittel is not None else None, "anomalie": anomalie,
            "technik_text": ttxt, "pruefhinweis": pruef,
            "ereignisse": [e["id"] for e in treffer[:12]],
        })
    return res


def _teilindex(inds: list[dict], index: str) -> float:
    sel = [i for i in inds if i["index"] == index]
    if not sel:
        return 0.0
    w = sum(i["gewicht"] for i in sel)
    mittel = sum(i["gewicht"] * i["stufe"] for i in sel) / w / 4 * 100
    spitze = max(i["stufe"] for i in sel) * 25
    return round(0.6 * mittel + 0.4 * spitze, 1)


def konvergenz(inds: list[dict], ereignisse: list[dict], tech_b: dict) -> dict:
    """Unabhaengige Signalarten der letzten 24 h zur selben Region."""
    g24 = now_utc() - timedelta(hours=24)
    neu = [e for e in ereignisse if (_parse_zeit(e["zeit"]) or g24) >= g24]
    eskal = [e for e in neu if set(e["wer"]) & {"RU", "BY"} or _hat(norm(e["titel"]), ["airspace", "drone", "luftraum", "drohne", "cable", "kabel", "border", "grenze"])]
    arten = []
    if any(e["status"] == "bestätigt (offiziell)" for e in eskal):
        arten.append("offizielle Meldung")
    if len({q["verlag"] for e in eskal for q in e["quellen"]}) >= 4:
        arten.append("Medienhäufung")
    if any(i["anomalie"] for i in inds if i["index"] == "eskalation"):
        arten.append("Meldungsanomalie")
    if tech_b["adsb"].get("anomalie") or tech_b["adsb"]["stufe"] >= 2:
        arten.append("Militärflüge ADS-B")
    if tech_b["notam"]["stufe"] >= 2:
        arten.append("Luftraumsperren NOTAM")
    if tech_b["ais"]["stufe"] >= 2:
        arten.append("Marine AIS")
    stark = len(arten) >= 3 and ("offizielle Meldung" in arten or any("ADS-B" in a or "NOTAM" in a or "AIS" in a for a in arten))
    return {"aktiv": len(arten) >= 2, "stark": stark, "signale": arten,
            "text": f"{len(arten)} unabhängige Signalarten in 24 h: " + (", ".join(arten) or "keine")}


def gesamt(inds: list[dict], konv: dict) -> dict:
    esk = _teilindex(inds, "eskalation")
    verl = _teilindex(inds, "verlegung")
    stufe = 1 if esk < 25 else 2 if esk < 50 else 3 if esk < 68 else 4 if esk < 85 else 5
    grund = "Eskalationsindex"
    if konv["stark"] and stufe < 4:
        stufe, grund = stufe + 1, "Konvergenz mehrerer unabhängiger Signale"
    for i in inds:
        if i["formell"] and i["stufe"] >= 3 and stufe < 4:
            stufe, grund = 4, f"formell: {i['name']}"
    return {"eskalation": esk, "verlegung": verl, "stufe": stufe, "stufe_text": GESAMT_TEXT[stufe], "stufe_grund": grund}


# ---------------------------------------------------------------- Lauf

def _llm_anreichern(ereignisse: list[dict], llm_fn, cache: dict, max_n: int = 12) -> None:
    """Optional: Felder per Sprachmodell aus dem Titel praezisieren (llm_fn(prompt)->str, vom Server, z.B. Haiku).
    Nur Titel, keine Personendaten. Ergebnis ueberschreibt Regel-Felder nur, wenn nicht leer."""
    import json
    n = 0
    for e in ereignisse:
        if e["id"] in cache:
            e.update({k: v for k, v in cache[e["id"]].items() if v})
            continue
        if n >= max_n:
            break
        prompt = ("Extrahiere aus der Schlagzeile nur explizit genannte Angaben als JSON mit den Schlüsseln "
                  "wer (Liste Länderkürzel/Organisation), was (kurz, Deutsch), wie_viel (Liste, z.B. '3000 Soldaten'), "
                  "wohin (Ort/Region, Deutsch), wann (Datum/Zeitraum falls genannt). Nichts schätzen, unbekannt = leer.\n"
                  f"Schlagzeile: {e['titel']}")
        try:
            roh = llm_fn(prompt)
            j = json.loads(roh[roh.find("{"): roh.rfind("}") + 1])
        except Exception:  # noqa: BLE001
            continue
        f = {"wer_llm": j.get("wer") or [], "was_llm": j.get("was") or "", "wie_viel_llm": j.get("wie_viel") or [],
             "wohin_llm": j.get("wohin") or "", "wann_llm": j.get("wann") or ""}
        cache[e["id"]] = f
        e.update(f)
        n += 1


def update(force: bool = False, news_items: list[dict] | None = None, llm_fn=None) -> dict:
    """Voller Lauf: Quellen, Technik, Bewertung. news_items = Meldungen aus bestehenden Server-Feeds."""
    os.makedirs(DATA_DIR, exist_ok=True)
    alt = load_json(STATE_FILE, {})
    tech = alt.get("technik", {})
    letzte_adsb = _parse_zeit(tech.get("adsb_zeit"))
    if force or not letzte_adsb or now_utc() - letzte_adsb >= timedelta(minutes=ADSB_INTERVALL_MIN):
        adsb_lauf(load_json(KATALOG_FILE, {}), tech)
    letzt = _parse_zeit(alt.get("aktualisiert"))
    if not force and letzt and now_utc() - letzt < timedelta(minutes=INTERVALL_MIN):
        alt["technik"] = tech
        save_json(STATE_FILE, alt)
        return alt
    kat = load_json(KATALOG_FILE, {})
    notam_lauf(kat, tech)
    diagnose: dict = {}
    neu = sammeln(kat, diagnose)
    for it in news_items or []:
        t = norm(it.get("titel", ""))
        if relevant(t, None, kat):
            neu.append(meldung_aus_item(it, None, kat))
    # Rohmeldungen 14 Tage behalten (fuer Bestaetigung ueber Zeit und Verlauf)
    roh = {m["link"] or m["titel"]: m for m in alt.get("_roh", []) + neu}
    roh = [m for m in roh.values() if (_parse_zeit(m["zeit"]) or now_utc()) >= now_utc() - timedelta(days=14)]
    ereignisse = buendeln(roh)
    cache = alt.get("_llm_cache", {})
    if llm_fn:
        _llm_anreichern(ereignisse, llm_fn, cache)
    tech_b = {"adsb": adsb_bewertung(tech), "notam": notam_bewertung(tech), "ais": ais_bewertung(tech)}
    hist = alt.get("verlauf", [])
    inds = bewerte(kat, ereignisse, tech_b, hist)
    konv = konvergenz(inds, ereignisse, tech_b)
    g = gesamt(inds, konv)
    heute = datetime.now().strftime("%Y-%m-%d")
    hist = push_history(hist, {"datum": heute, "eskalation": g["eskalation"], "verlegung": g["verlegung"], "stufe": g["stufe"],
                               "stufen": {i["id"]: i["stufe"] for i in inds},
                               "meldungen": {i["id"]: i["gewichtet_7t"] for i in inds}})
    log = alt.get("veraenderungen", [])
    vorher = {i["id"]: i["stufe"] for i in alt.get("indikatoren", [])}
    for i in inds:
        if i["id"] in vorher and vorher[i["id"]] != i["stufe"]:
            log.append({"datum": heute, "id": i["id"], "name": i["name"], "von": vorher[i["id"]], "nach": i["stufe"], "grund": i["stufe_aus"]})
    if alt.get("stufe") and alt["stufe"] != g["stufe"]:
        log.append({"datum": heute, "id": "GESAMT", "name": "Gesamtstufe Ostflanke", "von": alt["stufe"], "nach": g["stufe"], "grund": g["stufe_grund"]})
    ereignisse.sort(key=lambda e: (e["zeit"] or ""), reverse=True)
    state = {
        "modul": "ostflanke", "aktualisiert": iso(now_utc()), "prioritaet": 1, **g,
        "trend_7t": {"eskalation": trend(hist, "eskalation"), "verlegung": trend(hist, "verlegung")},
        "konvergenz": konv, "indikatoren": inds, "ereignisse": ereignisse[:150],
        "technik": tech, "technik_bewertung": tech_b, "verlauf": hist, "veraenderungen": log[-200:],
        "diagnose": diagnose, "datenluecken": [k for k, v in tech_b.items() if not v.get("ok")],
        "orte": [{k: o[k] for k in ("id", "name", "lat", "lon", "art")} for o in kat["orte"]],
        "spannungsfall": spannungsfall_beitrag(inds, kat),
        "hinweis": "Nur offene Quellen. Keine eingestuften Lagedaten. RU/BY melden Verlegungen nicht oder irreführend; "
                   "Kriegsschiffe/Kampfjets oft ohne AIS/ADS-B. Leere Felder = von der Quelle nicht angegeben.",
        "_roh": roh[-800:], "_llm_cache": {k: v for k, v in cache.items() if k in {e["id"] for e in ereignisse}},
    }
    save_json(STATE_FILE, state)
    return state


def get_state(oeffentlich: bool = True) -> dict:
    s = load_json(STATE_FILE, {}) or update(force=True)
    if oeffentlich:
        s = {k: v for k, v in s.items() if not k.startswith("_")}
        t = dict(s.get("technik", {}))
        t.pop("adsb_tage", None)
        s["technik"] = t
    return s


# ---------------------------------------------------------------- Anbindung

def spannungsfall_beitrag(inds: list[dict] | None = None, kat: dict | None = None) -> dict:
    """{Spannungsfall-Indikator-ID: {stufe, text}} fuer spannungsfall.update(extern=...)."""
    if inds is None:
        inds = load_json(STATE_FILE, {}).get("indikatoren", [])
    kat = kat or load_json(KATALOG_FILE, {})
    by = {i["id"]: i for i in inds}
    out = {}
    for sid, quellen in kat.get("spannungsfall_verknuepfung", {}).items():
        if sid.startswith("_"):
            continue
        sel = [by[q] for q in quellen if q in by]
        if not sel:
            continue
        top = max(sel, key=lambda i: i["stufe"])
        if sid.startswith("pruef_"):
            if top.get("pruefhinweis") or top["stufe"] >= 3:
                out[sid[6:]] = {"pruef": f"Ostflanke {top['id']}: {top.get('pruefhinweis') or top['kriterium']}"}
            continue
        out[sid] = {"stufe": top["stufe"], "text": f"Ostflanke {top['id']} {top['name']}: Stufe {top['stufe']}/4 ({top['kriterium']})"}
    return out


def fruehwarnung_signale(state: dict | None = None) -> list[dict]:
    s = state or get_state()
    out = []
    if s.get("stufe", 1) >= 2:
        out.append({"bereich": "Ostflanke", "prioritaet": 1, "titel": f"Ostflanke Stufe {s['stufe']}: {s['stufe_text']}",
                    "stufe": s["stufe"], "text": f"Eskalation {s['eskalation']}/100 ({s['stufe_grund']})", "quelle": "Ostflanken-Modell"})
    for i in s.get("indikatoren", []):
        if i["anomalie"] or (i["index"] == "eskalation" and i["stufe"] >= 3 and i["stufe_aus"] != "Basis"):
            out.append({"bereich": "Ostflanke", "prioritaet": 1, "titel": i["name"], "stufe": min(5, i["stufe"] + 1),
                        "text": f"{i['meldungen_7t']} Ereignisse/7T" + (f" (Vorwochen {i['vorwochen_mittel']})" if i["vorwochen_mittel"] is not None else "")
                        + (f"; {i['technik_text']}" if i["technik_text"] else ""), "quelle": "Ostflanke"})
        if i["pruefhinweis"]:
            out.append({"bereich": "Ostflanke", "prioritaet": 1, "titel": "Prüfen: " + i["name"], "stufe": 4, "text": i["pruefhinweis"], "quelle": "Ostflanke"})
    return out


def konvergenz_anomalie(state: dict | None = None) -> dict | None:
    """Eintrag fuer die bestehende Fruehwarn-Liste (Schema wie Konvergenz im Server).
    kein_push=True, solange config ostflanke.push_aktiv nicht gesetzt ist (Push-Regeln unveraendert)."""
    s = state or get_state()
    k = s.get("konvergenz", {})
    if not k.get("aktiv"):
        return None
    return {"kat": "konvergenz", "region": "Ostflanke/Baltikum", "prioritaet": 1,
            "stufe": "stark" if k["stark"] else "mittel", "signale": k["signale"], "text": k["text"],
            "aussagekraft": {"stufe": "hoch" if k["stark"] else "mittel"},
            "kein_push": not _cfg().get("ostflanke", {}).get("push_aktiv", False)}


def push_kandidaten(state: dict | None = None, vorher_stufe: int | None = None) -> list[dict]:
    """Vorschlag Ostflanken-Alarm. Wirkt nur, wenn config ostflanke.push_aktiv = true (siehe push.lauf)."""
    if not _cfg().get("ostflanke", {}).get("push_aktiv", False):
        return []
    s = state or get_state()
    out = []
    sprung = s["stufe"] - (vorher_stufe if vorher_stufe is not None else s["stufe"])
    if s["stufe"] >= 4 or sprung >= 2:
        out.append({"id": f"ostflanke-stufe-{s['stufe']}", "modul": "ostflanke", "stufe": s["stufe"], "sprung": sprung,
                    "titel": f"Ostflanke: Stufe {s['stufe']}/5", "text": f"{s['stufe_text']}. {s['stufe_grund']}."})
    for e in s.get("ereignisse", [])[:30]:
        t = norm(e["titel"])
        if e["status"] == "bestätigt (offiziell)" and _hat(t, ["article 4", "artikel 4", "art. 4", "article 5", "artikel 5", "mobiliz", "mobilmach", "martial law"]):
            out.append({"id": f"ostflanke-formell-{e['id']}", "modul": "ostflanke", "formell": True, "stufe": 5,
                        "titel": "Ostflanke: formeller Schritt", "text": e["titel"][:300]})
    return out


def lage_kontext(state: dict | None = None, max_zeichen: int = 1800) -> str:
    s = state or get_state()
    z = [f"OSTFLANKE / BALTIKUM / SUWALKI (Priorität 1): Stufe {s.get('stufe')}/5 ({s.get('stufe_text')}; {s.get('stufe_grund')}). "
         f"Eskalation {s.get('eskalation')} {s.get('trend_7t', {}).get('eskalation', '')}, NATO-Verlegungen {s.get('verlegung')} (0-100). "
         f"{s.get('konvergenz', {}).get('text', '')}"]
    for i in sorted(s.get("indikatoren", []), key=lambda i: -i["stufe"])[:5]:
        z.append(f"- {i['id']} {i['name']}: {i['stufe']}/4 ({i['kriterium']}); {i['meldungen_7t']} Ereignisse/7T" + (" ANOMALIE" if i["anomalie"] else ""))
    z.append("Neueste Bewegungen/Vorfälle (wer|was|wie viel|wohin|Status):")
    for e in s.get("ereignisse", [])[:8]:
        z.append(f"· {(e.get('zeit') or '')[:16]} {','.join(e['wer']) or '?'} | {', '.join(e['was'][:2]) or '?'} | "
                 f"{', '.join(e['wie_viel']) or '-'} | {e['wohin'][0]['name'] if e['wohin'] else '-'} | {e['status']} ({e['verl']}) :: {e['titel'][:100]}")
    tb = s.get("technik_bewertung", {})
    z.append("Technik: " + " | ".join(f"{k}: {v.get('text')}" for k, v in tb.items()))
    return "\n".join(z)[:max_zeichen]


LAGE_ANWEISUNG = (
    "Der Abschnitt 'Ostflanke / Baltikum / Suwalki-Korridor' steht IMMER an erster Stelle der Lage. "
    "Inhalt: Gesamtstufe, dann konkret wer was wie viel wohin verlegt (nur genannte Angaben, keine Schätzungen), "
    "jeweils mit Status bestätigt/unbestätigt bzw. Eigenangabe RU/BY. NATO-Verstärkung (Abschreckung) getrennt von "
    "Eskalationssignalen nennen. Technische Signale (Militärflüge, NOTAM, AIS) nur bei Auffälligkeit. "
    "Danach Wirkung auf 'Spannungsfall Deutschland' in einem Satz. 3-6 Sätze, nüchtern, mit Zahlen."
)


def diagnose() -> None:
    """Auf dem Server einmal ausfuehren: zeigt je Quelle, ob RSS/Google News Daten liefert."""
    kat = load_json(KATALOG_FILE, {})
    d: dict = {}
    ms = sammeln(kat, d)
    tech: dict = {}
    adsb_lauf(kat, tech)
    for k, v in d.items():
        print(f"{k:40s} {v}")
    print(f"relevante Meldungen: {len(ms)}; ADS-B Region: {len(tech.get('adsb_jetzt', []))} {tech.get('adsb_fehler', '')}")


if __name__ == "__main__":
    import sys
    if "--diagnose" in sys.argv:
        diagnose()
    else:
        st = update(force=True)
        print(lage_kontext(st))
