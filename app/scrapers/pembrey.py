"""Pembrey Circuit (Wales) — https://pembreycircuit.co.uk/

Each event is an <article class="EventCard">:
  .EventCard-title     -> "Car Tracdayz" / "Bike Tracdayz"
  .EventCard-date      -> "9 May 2026"
  a (.EventCard-inner) -> relative href to the event page
  <p>...description...</p>

The site was redesigned in autumn 2026 and /car-track-days is now a
marketing page: its own "View Dates" button points at the /events listing
read below, so that is what this follows. As of 2026-11-01 that listing
renders "no events" — Pembrey's last day was 3 October and nothing is up
for 2027 — so the EventCard markup above cannot be re-verified against
live data. It is kept because the parser is cheap and known-good, but
expect to re-check the card classes against the new design the first time
dates reappear; nothing on the page uses .EventCard today.

The wait selector therefore accepts either an EventCard or the news
ArticleCard that the empty listing does render. Waiting on .EventCard
alone spent the full 30s timeout on each of two pages, twice a night, to
learn nothing.
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "pembrey"
ORGANISER = "Pembrey Circuit"
_EVENTS = "https://pembreycircuit.co.uk/events?category="
URLS = {
    "car":  _EVENTS + "track-days%2Ctest-days",
    "bike": _EVENTS + "bike-track-days",
}
# Only an EventCard becomes an event; ArticleCard is the news list and is
# here so the render stops waiting as soon as the page has settled.
WAIT_SELECTOR = ".EventCard, .ArticleCard"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    for vehicle, url in URLS.items():
        tree = await get_html_js(url, wait_selector=WAIT_SELECTOR)
        (DEBUG_DIR / f"pembrey_{vehicle}.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")
        for card in tree.css(".EventCard"):
            ev = _parse(card, vehicle)
            if ev:
                out.append(ev)
    return out


def _parse(card: Node, vehicle: str) -> Optional[RawEvent]:
    title_node = card.css_first(".EventCard-title")
    date_node = card.css_first(".EventCard-date")
    if not title_node or not date_node:
        return None
    title = title_node.text(strip=True)
    m = DATE_RE.search(date_node.text(strip=True))
    if not m:
        return None
    try:
        event_date = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date()
    except ValueError:
        try:
            event_date = datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {m.group(3)}", "%d %b %Y").date()
        except ValueError:
            return None

    link = card.css_first("a.EventCard-inner") or card.css_first("a")
    href = link.attributes.get("href", "") if link else ""
    if href and not href.startswith("http"):
        href = "https://pembreycircuit.co.uk/" + href.lstrip("/")
    if not href:
        href = URLS[vehicle]
    sku = href.rstrip("/").rsplit("/", 1)[-1]

    desc_node = card.css_first("p")
    desc = desc_node.text(separator=" ", strip=True) if desc_node else None

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw="Pembrey", event_date=event_date, booking_url=href,
        title=f"{title} — {vehicle.title()}",
        notes=desc, vehicle_type=vehicle, session="day", external_id=f"{vehicle}|{sku}",
    )
