"""GEDLICH Racing — https://gedlich-racing.com/en/calendar-booking/

DOM per event:
  div.date-item
    span.booking            -> "book now!" / "sold out!"
    a[href]                 -> per-event detail page (booking)
    p.dates                 -> "28.05.2026" or multi-day "21.07.2026 / 22.07.2026"
      span.trackday-format  -> "Format: Open Pitlane"
    p.event                 -> "Race Test Oschersleben"
    p.booked span           -> "25 free slots ..." (when bookable)
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "gedlich"
ORGANISER = "GEDLICH Racing"
LISTING_URL = "https://gedlich-racing.com/en/calendar-booking/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
SLOTS_RE = re.compile(r"(\d+)\s+free\s+slot", re.I)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".date-item")
    (DEBUG_DIR / "gedlich.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")
    out: list[RawEvent] = []
    for card in tree.css(".date-item"):
        ev = _parse(card)
        if ev:
            out.append(ev)
    return out


def _parse(card: Node) -> Optional[RawEvent]:
    link = card.css_first("a")
    if not link:
        return None
    href = link.attributes.get("href") or LISTING_URL

    title_node = card.css_first(".event")
    title = title_node.text(strip=True) if title_node else ""

    date_node = card.css_first(".dates")
    if not date_node:
        return None
    # First date in the .dates text — multi-day events use the start date.
    date_text = date_node.text(strip=True)
    m = DATE_RE.search(date_text)
    if not m:
        return None
    try:
        event_date = datetime.strptime(f"{m.group(1)}.{m.group(2)}.{m.group(3)}", "%d.%m.%Y").date()
    except ValueError:
        return None

    booking_node = card.css_first(".booking")
    booking_text = (booking_node.text(strip=True) if booking_node else "").lower()
    sold_out = "sold out" in booking_text

    spaces_left = None
    booked_node = card.css_first(".booked span")
    if booked_node:
        sm = SLOTS_RE.search(booked_node.text(strip=True))
        if sm:
            spaces_left = int(sm.group(1))

    fmt_node = card.css_first(".trackday-format")
    fmt = fmt_node.text(strip=True).replace("Format:", "").strip() if fmt_node else None
    notes = fmt or None

    # Multi-day events flagged as packages.
    is_package = bool(re.search(r"\d{2}\.\d{2}\.\d{4}\s*/\s*\d{2}\.\d{2}\.\d{4}", date_text))

    # Circuit name: title looks like "Race Test Oschersleben". Strip the prefix.
    circuit_raw = re.sub(r"^(Race\s+Test|Endless\s+Summer|Trackday|Nordschleifen[a-z]*)\s+", "", title, flags=re.I).strip() or title

    sku = href.rstrip("/").rsplit("/", 1)[-1]

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=href,
        title=title, currency="EUR", region="EU",
        sold_out=sold_out, spaces_left=spaces_left if not sold_out else 0,
        stock_status="Sold Out" if sold_out else None,
        is_package=is_package, notes=notes,
        session="day", external_id=sku,
    )
