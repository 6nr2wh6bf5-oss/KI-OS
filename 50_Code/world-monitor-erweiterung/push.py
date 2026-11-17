"""Push-Meldungen aufs iPhone bei sehr hoher Aussagekraft (ntfy oder Pushover).

config.json:
  "push": {
    "dienst": "ntfy",                 # oder "pushover"
    "ntfy_topic": "<langer Zufallsname>", "ntfy_server": "https://ntfy.sh",
    "pushover_token": "...", "pushover_user": "...",
    "max_pro_tag": 3, "ruhe_von": 23, "ruhe_bis": 7,
    "fruehwarn_min_dauer_min": 60    # optional, Standard 60
  }

Aufruf: push.lauf(anomalien, energie_state, spannung_state) nach jedem Update der Fruehwarnung/Module
(anomalien=None: Fruehwarnung in diesem Lauf nicht auswerten).
Kandidat = {"id": eindeutig, "titel", "text", "stufe": 1-5, "aussagekraft": 0-1 oder "sehr hoch"..., "formell": bool}
Nur Kandidaten, die kritisch() erfuellen, werden gesendet. Keine Personendaten im Text.

Damit die Meldungen selten bleiben (Ziel 1-2 pro Woche), gilt:
- Fruehwarnung: nur Konvergenz (mehrere unabhaengige Signale zum selben Konflikt), die mindestens
  60 Min. ununterbrochen besteht. Einzelne Anomalien melden sich nicht.
- Jede Meldung (gleiche id) hoechstens einmal in 7 Tagen, auch wenn der Zustand andauert.
- Ruhezeit und Tageslimit verschieben nur: was kritisch bleibt, kommt spaeter.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from wm_common import load_json, save_json

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("WM_DATA_DIR", os.path.join(BASE, "data"))
CONFIG_FILE = os.environ.get("WM_CONFIG", os.path.join(BASE, "config.json"))
LOG_FILE = os.path.join(DATA_DIR, "push_log.json")
VORHER_FILE = os.path.join(DATA_DIR, "push_vorher.json")
SPERRE_H = 7 * 24   # gleiche Meldung hoechstens einmal pro Woche
URL_MONITOR = "https://world-monitor.taildd2cb1.ts.net"

AUSSAGE_HOCH = {"sehr hoch", "hoch", "very high", "high"}


def _aussage_ok(a) -> bool:
    if isinstance(a, (int, float)):
        return a >= 0.85
    return str(a).strip().lower() in ("sehr hoch", "very high")


def kritisch(k: dict) -> bool:
    """Schwelle 'sehr sehr hohe Aussagekraft'."""
    if k.get("formell"):
        return True
    if k.get("stufe", 0) >= 5 and _aussage_ok(k.get("aussagekraft", 0)):
        return True
    if k.get("modul") in ("energie", "spannungsfall") and (k.get("stufe", 0) >= 4 or k.get("sprung", 0) >= 2):
        return True
    return False


def kandidaten_aus_modulen(energie_state: dict, spannung_state: dict, vorher: dict) -> list[dict]:
    """Kandidaten aus den Modulen: Gesamtstufe >= 4, Sprung um >= 2 Stufen, formelle Ausloeser."""
    out = []
    for mod, s in (("energie", energie_state), ("spannungsfall", spannung_state)):
        if not s:
            continue
        alt = vorher.get(mod, s.get("stufe", 1))
        out.append({"id": f"{mod}-stufe-{s['stufe']}", "modul": mod, "stufe": s["stufe"],
                    "sprung": s["stufe"] - alt,
                    "titel": f"{'Energie' if mod == 'energie' else 'Spannungsfall DE'}: Stufe {s['stufe']}/5",
                    "text": s.get("stufe_text", "")})
    for i in (spannung_state or {}).get("indikatoren", []):
        if i.get("formell") and i.get("stufe", 0) >= 3:
            out.append({"id": f"ausloeser-{i['id']}", "formell": True, "stufe": 5,
                        "titel": f"Ausgelöst: {i['name']}", "text": i.get("text", "")})
    return out


def kandidaten_aus_fruehwarnung(anomalien: list[dict], seit: dict, jetzt: datetime, min_dauer_min: int = 60) -> list[dict]:
    """Kandidaten aus der Fruehwarnung: nur Konvergenz, die seit min_dauer_min ununterbrochen besteht.
    seit (id -> Zeitpunkt der ersten Beobachtung) wird hier fortgeschrieben; was verschwindet, beginnt von vorn.
    Die Aussagekraft kennt als hoechste Kategorie «hoch»; nur diese zaehlt und gilt hier als «sehr hoch»."""
    out, aktiv = [], set()
    for a in anomalien or []:
        if a.get("kat") != "konvergenz" or a.get("stufe") != "stark" or a.get("filter"):
            continue
        if (a.get("aussagekraft") or {}).get("stufe") != "hoch":
            continue
        kid = f"konvergenz|{a['region']}"   # ohne die Signal-Aufzaehlung, die wechselt von Lauf zu Lauf
        aktiv.add(kid)
        seit.setdefault(kid, jetzt.isoformat(timespec="seconds"))
        if jetzt - datetime.fromisoformat(seit[kid]) >= timedelta(minutes=min_dauer_min):
            out.append({"id": kid, "stufe": 5, "aussagekraft": "sehr hoch", "titel": f"Frühwarnung: {a['region']}",
                        "text": f"{a.get('text', '')}. Besteht seit mindestens {min_dauer_min} Minuten."})
    for kid in set(seit) - aktiv:
        del seit[kid]
    return out


def _senden(cfg: dict, titel: str, text: str, prio_max: bool) -> None:
    if cfg.get("dienst", "ntfy") == "pushover":
        data = urllib.parse.urlencode({"token": cfg["pushover_token"], "user": cfg["pushover_user"],
                                       "title": titel, "message": text, "url": URL_MONITOR,
                                       "priority": 1 if prio_max else 0}).encode()
        urllib.request.urlopen("https://api.pushover.net/1/messages.json", data=data, timeout=15).read()
    else:
        # JSON statt Kopfzeilen, damit Umlaute und Gedankenstriche im Titel sicher ankommen
        daten = {"topic": cfg["ntfy_topic"], "title": titel, "message": text, "priority": 5 if prio_max else 4,
                 "tags": ["rotating_light"], "click": URL_MONITOR}
        req = urllib.request.Request(cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/") + "/", method="POST",
                                     data=json.dumps(daten).encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()


def _gesperrt(log: list[dict], kid: str, jetzt: datetime) -> bool:
    return any(e["id"] == kid and datetime.fromisoformat(e["zeit"]) > jetzt - timedelta(hours=SPERRE_H) for e in log)


def pruefen(kandidaten: list[dict], jetzt: datetime | None = None, dry_run: bool = False,
            log_datei: str | None = None) -> list[dict]:
    """dry_run sendet nichts. Ohne log_datei schreibt dry_run auch nichts (das echte Log bleibt unberuehrt);
    mit log_datei wird dorthin protokolliert, fuer Rueckrechnungen ueber mehrere Laeufe."""
    cfg = load_json(CONFIG_FILE, {}).get("push", {})
    if not cfg or not (cfg.get("ntfy_topic") or cfg.get("pushover_token")):
        return []
    jetzt = jetzt or datetime.now()
    os.makedirs(DATA_DIR, exist_ok=True)
    log = load_json(log_datei or LOG_FILE, [])
    log = [e for e in log if datetime.fromisoformat(e["zeit"]) > jetzt - timedelta(days=30)]
    heute = [e for e in log if e["zeit"][:10] == jetzt.strftime("%Y-%m-%d")]
    ruhe = jetzt.hour >= cfg.get("ruhe_von", 23) or jetzt.hour < cfg.get("ruhe_bis", 7)
    gesendet = []
    for k in sorted(kandidaten, key=lambda x: -x.get("stufe", 0)):
        if not kritisch(k):
            continue
        if _gesperrt(log, k["id"], jetzt):
            continue
        if ruhe and k.get("stufe", 0) < 5 and not k.get("formell"):
            continue
        if len(heute) + len(gesendet) >= cfg.get("max_pro_tag", 3) and not k.get("formell"):
            continue
        if not dry_run:
            try:
                _senden(cfg, k["titel"][:120], (k.get("text") or "")[:400], k.get("stufe", 0) >= 5)
            except Exception:  # noqa: BLE001
                continue
        e = {"id": k["id"], "zeit": jetzt.isoformat(timespec="seconds"), "titel": k["titel"]}
        log.append(e)
        gesendet.append(e)
    if not dry_run or log_datei:
        save_json(log_datei or LOG_FILE, log)
    return gesendet


def lauf(anomalien: list[dict] | None, energie_state: dict, spannung_state: dict, jetzt: datetime | None = None,
         dry_run: bool = False, log_datei: str | None = None, zustand_datei: str | None = None) -> list[dict]:
    """Ein Pruefdurchgang: Kandidaten bilden, senden, Stufen und Beobachtungszeiten merken."""
    jetzt = jetzt or datetime.now()
    z = load_json(zustand_datei or VORHER_FILE, {})
    module = kandidaten_aus_modulen(energie_state, spannung_state, z)
    kandidaten = list(module)
    if anomalien is not None:
        seit = z.setdefault("fruehwarn_seit", {})
        dauer = load_json(CONFIG_FILE, {}).get("push", {}).get("fruehwarn_min_dauer_min", 60)
        kandidaten += kandidaten_aus_fruehwarnung(anomalien, seit, jetzt, dauer)
    gesendet = pruefen(kandidaten, jetzt, dry_run, log_datei)
    # Ein Sprung, der wegen Ruhezeit, Tageslimit oder Sendefehler nicht rausging, bleibt offen: Stufe nicht fortschreiben
    log = load_json(log_datei or LOG_FILE, [])
    for mod, s in (("energie", energie_state), ("spannungsfall", spannung_state)):
        if not s:
            continue
        k = next((x for x in module if x.get("modul") == mod), None)
        if not (k and kritisch(k) and not _gesperrt(log, k["id"], jetzt)):
            z[mod] = s["stufe"]
    if not dry_run or zustand_datei:
        os.makedirs(DATA_DIR, exist_ok=True)
        save_json(zustand_datei or VORHER_FILE, z)
    return gesendet


def test() -> None:
    cfg = load_json(CONFIG_FILE, {}).get("push", {})
    _senden(cfg, "World Monitor: Testmeldung", "Push-Meldungen sind eingerichtet.", False)


if __name__ == "__main__":
    test()
