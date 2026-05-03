"""Goldtrack — https://goldtrack.co.uk/racing/track-days/

WordPress + Avada/Fusion Builder. Each event is an <article class="... category-track-days ...">.
Each article contains a link with the full title like:
  "Anglesey Int Circuit Track day Monday 18th May 2026"
URL slug: e.g. /anglesey-circuit-track-day-mon-18-may-goldtrack-2026/
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "goldtrack"
ORGANISER = "Goldtrack"
LISTING_URL = "https://goldtrack.co.uk/racing/track-days/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

TITLE_DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})")
SLUG_DATE_RE = re.compile(r"(\d{1,2})-([a-z]+)-(?:goldtrack-)?(\d{4})", re.I)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector="article.category-track-days")
    (DEBUG_DIR / "goldtrack.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    seen_urls = set()
    for art in tree.css("article.category-track-days"):
        for a in art.css("a[aria-label]"):
            label = a.attributes.get("aria-label") or ""
            href = a.attributes.get("href") or ""
            if not label or href in seen_urls:
                continue
            seen_urls.add(href)
            ev = _parse(label, href)
            if ev:
                out.append(ev)
            break
    return out


def _parse(title: str, href: str) -> Optional[RawEvent]:
    event_date = _date_from_title(title) or _date_from_slug(href)
    if not event_date:
        return None

    # circuit name = leading words before "Circuit" / "Track"
    circuit_raw = re.split(r"\s+(?:Circuit|Track\s*day|GP|Int|International|Grand)", title, maxsplit=1, flags=re.I)[0].strip() or title
    sku = href.rstrip("/").rsplit("/", 1)[-1]

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=href,
        title=title, session="day", external_id=sku,
    )


def _date_from_title(t: str) -> Optional[date]:
    m = TITLE_DATE_RE.search(t)
    if not m:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt).date()
        except ValueError:
            continue
    return None


def _date_from_slug(href: str) -> Optional[date]:
    m = SLUG_DATE_RE.search(href.lower())
    if not m:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt).date()
        except ValueError:
            continue
    return None
