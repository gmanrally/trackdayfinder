"""Kirkistown Racing Circuit (NI) — https://kirkistown.com/

WordPress + The Events Calendar plugin. We crawl the car-events category list
which uses standard <article class="tribe_events"> markup with <time datetime>
and a title link. We then filter to track-day events (skip race meetings, sprints).
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "kirkistown"
ORGANISER = "Kirkistown Racing Circuit"
LISTING_URLS = [
    "https://kirkistown.com/events/category/car-events/",
    "https://kirkistown.com/events/",
]
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    seen = set()
    for url in LISTING_URLS:
        tree = await get_html_js(url, wait_selector="article.tribe_events")
        for art in tree.css("article.tribe_events"):
            ev = _parse(art)
            if not ev:
                continue
            key = (ev.event_date, ev.title)
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
    return out


def _parse(art: Node) -> Optional[RawEvent]:
    title_link = art.css_first(".tribe-events-calendar-list__event-title-link, h3 a")
    if not title_link:
        return None
    title = title_link.text(strip=True)
    href = title_link.attributes.get("href") or LISTING_URLS[0]

    # Filter: real trackdays only — drop race meetings, sprints, championship rounds.
    low = title.lower()
    if not any(k in low for k in ("track day", "trackday", "track skills", "trackskills")):
        return None
    if any(k in low for k in ("race meeting", "championship", "sprint", "rally", "festival")):
        return None

    time_node = art.css_first("time")
    iso = (time_node.attributes.get("datetime") if time_node else "") or ""
    try:
        event_date = datetime.fromisoformat(iso.split("T")[0]).date()
    except ValueError:
        return None

    vehicle = "bike" if "bike" in low or "motorcycle" in low or "motorbike" in low else "car"
    sku = href.rstrip("/").rsplit("/", 1)[-1]

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw="Kirkistown", event_date=event_date, booking_url=href,
        title=title, vehicle_type=vehicle, session="day", external_id=sku,
    )
