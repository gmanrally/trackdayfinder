"""Pembrey Circuit (Wales) — https://pembreycircuit.co.uk/

Two listing pages — car and bike trackdays.
Each event is an <article class="EventCard">:
  .EventCard-title     -> "Car Tracdayz" / "Bike Tracdayz"
  .EventCard-date      -> "9 May 2026"
  a (.EventCard-inner) -> relative href to the event page
  <p>...description...</p>
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
URLS = {
    "car":  "https://pembreycircuit.co.uk/car-track-days?category=track-days",
    "bike": "https://pembreycircuit.co.uk/bike-track-days?category=bike-track-days",
}
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    for vehicle, url in URLS.items():
        tree = await get_html_js(url, wait_selector=".EventCard")
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
