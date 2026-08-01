"""Ollie's Secret Track Days — https://linktr.ee/olliessecrettrackdays

Small UK organiser running low-key days at Three Sisters, Curborough,
Bicester, Castle Combe. No booking site — events are posted as links on a
Linktree, each pointing at a Google Form to register. Linktree embeds all
links as JSON in a <script id="__NEXT_DATA__">; we read that.

Link titles look like:
  "Three Sisters - Mon 03 Aug 26"
  "Curborough - 20 Aug 26 - SOLD OUT"
  "Bicester - Fri 21 Aug 26"
"""
from __future__ import annotations
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import httpx
from ._base import RawEvent, UA

SOURCE_SLUG = "ollies_secret"
ORGANISER = "Ollie's Secret Track Days"
LINKTREE_URL = "https://linktr.ee/olliessecrettrackdays"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

CIRCUIT_KEYWORDS = [
    ("three sisters", "Three Sisters"),
    ("curborough",    "Curborough"),
    ("bicester",      "Bicester"),
    ("castle combe",  "Castle Combe"),
    ("anglesey",      "Anglesey"),
    ("mallory",       "Mallory Park"),
    ("blyton",        "Blyton Park"),
]

# "Mon 03 Aug 26" / "20 Aug 26" / "Tue 15 Sep 26" — optional weekday, 2-digit year.
DATE_RE = re.compile(
    r"(?:mon|tue|wed|thu|fri|sat|sun)?\.?\s*"
    r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{2,4})",
    re.I,
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def _iter_links(obj, out: list[tuple[str, str]]):
    if isinstance(obj, dict):
        title, url = obj.get("title"), obj.get("url")
        if isinstance(title, str) and isinstance(url, str):
            out.append((title, url))
        for v in obj.values():
            _iter_links(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _iter_links(v, out)


# Linktree 403s our default bot UA — send full browser-like headers.
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(headers=_BROWSER_HEADERS, timeout=20.0,
                                 follow_redirects=True) as c:
        r = await c.get(LINKTREE_URL)
        r.raise_for_status()
        html = r.text
    (DEBUG_DIR / "ollies_secret.html").write_text(html, encoding="utf-8", errors="ignore")

    m = NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    pairs: list[tuple[str, str]] = []
    _iter_links(data, pairs)

    out: list[RawEvent] = []
    seen: set[str] = set()
    for title, url in pairs:
        ev = _build(title, url)
        if ev and ev.external_id not in seen:
            seen.add(ev.external_id)
            out.append(ev)
    return out


def _build(title: str, url: str) -> Optional[RawEvent]:
    low = title.lower()
    circuit = None
    for kw, name in CIRCUIT_KEYWORDS:
        if kw in low:
            circuit = name
            break
    if not circuit:
        return None  # not an event link (subscribe / ads / track hire)

    dm = DATE_RE.search(title)
    if not dm:
        return None
    day_s, month_s, year_s = dm.group(1), dm.group(2), dm.group(3)
    yr = int(year_s)
    if yr < 100:
        yr += 2000
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            event_date = datetime.strptime(f"{day_s} {month_s} {yr}", fmt).date()
            break
        except ValueError:
            event_date = None
    if event_date is None or event_date < date.today():
        return None

    sold_out = "sold out" in low

    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=url,
        title="Track Day",
        currency="GBP",
        sold_out=sold_out,
        session="day",
        external_id=f"{circuit}|{event_date.isoformat()}",
        region="UK",
    )
