"""Gemeinsame Hilfsfunktionen fuer die Module Energie und Spannungsfall.

Nur Standardbibliothek (Server hat 1 GB RAM, keine neuen Abhaengigkeiten).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "WorldMonitor/1.0 (privat, Lagebild)"
TZ_CH = timezone(timedelta(hours=1))  # nur fuer Datumsstempel; Server-TZ ist Europe/Zurich


def http_get(url: str, headers: dict | None = None, timeout: int = 20) -> bytes:
    h = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url: str, headers: dict | None = None, timeout: int = 20):
    return json.loads(http_get(url, headers, timeout).decode("utf-8"))


def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- News (RSS)

def google_news_url(query: str, lang: str = "de", country: str = "DE") -> str:
    q = urllib.parse.quote(query + " when:7d")
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang}"


def parse_rss(raw: bytes) -> list[dict]:
    """RSS/Atom -> [{titel, link, quelle, zeit(iso)}]. Tolerant gegenueber Formatfehlern."""
    out = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        d = {c.tag.split("}")[-1]: c for c in it}
        titel = (d.get("title").text or "").strip() if d.get("title") is not None else ""
        link = ""
        if d.get("link") is not None:
            link = d["link"].text or d["link"].attrib.get("href", "")
        quelle = d["source"].text if d.get("source") is not None and d["source"].text else ""
        zeit = None
        for k in ("pubDate", "published", "updated"):
            if d.get(k) is not None and d[k].text:
                try:
                    zeit = parsedate_to_datetime(d[k].text)
                except (TypeError, ValueError):
                    try:
                        zeit = datetime.fromisoformat(d[k].text.replace("Z", "+00:00"))
                    except ValueError:
                        zeit = None
                break
        if titel:
            out.append({"titel": titel, "link": link.strip(), "quelle": quelle,
                        "zeit": iso(zeit) if zeit else None})
    return out


def fetch_news(queries: list[str], lang="de", country="DE", pause=1.0) -> list[dict]:
    items, seen = [], set()
    for q in queries:
        try:
            raw = http_get(google_news_url(q, lang, country))
        except Exception:
            continue
        for it in parse_rss(raw):
            key = re.sub(r"\W+", "", it["titel"].lower())[:90]
            if key in seen:
                continue
            seen.add(key)
            it["suchbegriff"] = q
            items.append(it)
        time.sleep(pause)
    return items


def norm(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def match_any(text: str, patterns: list[str]) -> bool:
    t = norm(text)
    return any(norm(p) in t for p in patterns)


def count_recent(items: list[dict], patterns: list[str], days: int,
                 exclude: list[str] | None = None, ref: datetime | None = None) -> tuple[int, list[dict]]:
    ref = ref or now_utc()
    grenze = ref - timedelta(days=days)
    treffer = []
    for it in items:
        if not it.get("zeit"):
            continue
        try:
            z = datetime.fromisoformat(it["zeit"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if z < grenze:
            continue
        text = it["titel"]
        if match_any(text, patterns) and not (exclude and match_any(text, exclude)):
            treffer.append(it)
    treffer.sort(key=lambda x: x["zeit"], reverse=True)
    return len(treffer), treffer


def stufe_aus_schwellen(wert: float, schwellen: list[float], absteigend=False) -> int:
    """schwellen = Grenzwerte fuer Stufe 1..4. absteigend=True: kleiner Wert = schlechter."""
    s = 0
    for i, g in enumerate(schwellen, start=1):
        if (wert <= g) if absteigend else (wert >= g):
            s = i
    return s


STUFEN_TEXT = {1: "Normal", 2: "Erhoeht", 3: "Angespannt", 4: "Kritisch", 5: "Akut"}


def index_zu_stufe(idx: float) -> int:
    return 1 if idx < 20 else 2 if idx < 40 else 3 if idx < 60 else 4 if idx < 80 else 5


def trend(history: list[dict], key: str, tage: int = 7) -> str:
    """Pfeil aus Verlauf (Liste {datum, key})."""
    if len(history) < 2:
        return "→"
    alt = None
    ziel = (now_utc() - timedelta(days=tage)).strftime("%Y-%m-%d")
    for h in history:
        if h["datum"] <= ziel:
            alt = h.get(key)
    if alt is None:
        alt = history[0].get(key)
    neu = history[-1].get(key)
    if alt is None or neu is None:
        return "→"
    d = neu - alt
    return "↑" if d >= 5 else "↓" if d <= -5 else "→"


def push_history(history: list[dict], eintrag: dict, max_tage: int = 400) -> list[dict]:
    """Ein Eintrag pro Tag (letzter Wert des Tages zaehlt)."""
    if history and history[-1]["datum"] == eintrag["datum"]:
        history[-1] = eintrag
    else:
        history.append(eintrag)
    return history[-max_tage:]
