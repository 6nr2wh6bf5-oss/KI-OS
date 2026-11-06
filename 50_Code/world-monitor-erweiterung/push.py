"""Push-Meldungen aufs iPhone bei sehr hoher Aussagekraft (ntfy oder Pushover).

config.json:
  "push": {
    "dienst": "ntfy",                 # oder "pushover"
    "ntfy_topic": "<langer Zufallsname>", "ntfy_server": "https://ntfy.sh",
    "pushover_token": "...", "pushover_user": "...",
    "max_pro_tag": 3, "ruhe_von": 23, "ruhe_bis": 7
  }

Aufruf: push.pruefen(kandidaten) nach jedem Update der Fruehwarnung/Module.
Kandidat = {"id": eindeutig, "titel", "text", "stufe": 1-5, "aussagekraft": 0-1 oder "sehr hoch"..., "formell": bool}
Nur Kandidaten, die kritisch() erfuellen, werden gesendet. Keine Personendaten im Text.
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
                        "titel": f"Ausgeloest: {i['name']}", "text": i.get("text", "")})
    return out


def _senden(cfg: dict, titel: str, text: str, prio_max: bool) -> None:
    if cfg.get("dienst", "ntfy") == "pushover":
        data = urllib.parse.urlencode({"token": cfg["pushover_token"], "user": cfg["pushover_user"],
                                       "title": titel, "message": text, "url": URL_MONITOR,
                                       "priority": 1 if prio_max else 0}).encode()
        urllib.request.urlopen("https://api.pushover.net/1/messages.json", data=data, timeout=15).read()
    else:
        url = cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/") + "/" + cfg["ntfy_topic"]
        req = urllib.request.Request(url, data=text.encode("utf-8"), method="POST", headers={
            "Title": titel.encode("utf-8").decode("latin-1", "replace"),
            "Priority": "max" if prio_max else "high", "Tags": "rotating_light",
            "Click": URL_MONITOR})
        urllib.request.urlopen(req, timeout=15).read()


def pruefen(kandidaten: list[dict], jetzt: datetime | None = None, dry_run: bool = False) -> list[dict]:
    cfg = load_json(CONFIG_FILE, {}).get("push", {})
    if not cfg or not (cfg.get("ntfy_topic") or cfg.get("pushover_token")):
        return []
    jetzt = jetzt or datetime.now()
    os.makedirs(DATA_DIR, exist_ok=True)
    log = load_json(LOG_FILE, [])
    log = [e for e in log if datetime.fromisoformat(e["zeit"]) > jetzt - timedelta(days=7)]
    heute = [e for e in log if e["zeit"][:10] == jetzt.strftime("%Y-%m-%d")]
    ruhe = jetzt.hour >= cfg.get("ruhe_von", 23) or jetzt.hour < cfg.get("ruhe_bis", 7)
    gesendet = []
    for k in sorted(kandidaten, key=lambda x: -x.get("stufe", 0)):
        if not kritisch(k):
            continue
        if any(e["id"] == k["id"] and datetime.fromisoformat(e["zeit"]) > jetzt - timedelta(hours=24) for e in log):
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
    save_json(LOG_FILE, log)
    return gesendet


def test() -> None:
    cfg = load_json(CONFIG_FILE, {}).get("push", {})
    _senden(cfg, "World Monitor: Testmeldung", "Push-Meldungen sind eingerichtet.", False)


if __name__ == "__main__":
    test()
