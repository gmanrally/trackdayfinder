"""Llandow Circuit (Wales) — https://www.llandow.com/

Per-discipline pages list dates inside a #tabcontent0 div ("Dates and Booking
Info" tab on the trackday page). Each date is a small card containing day,
month name, and the label "Car Trackday" / "Bike Trackday".
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "llandow"
ORGANISER = "Llandow Circuit"
URLS = {
    "car":  "https://www.llandow.com/trackdays/car-trackdays/",
    "bike": "https://www.llandow.com/trackdays/bike-trackdays/",
}
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

YEAR_RE = re.compile(r"(20\d{2})\s*Dates", re.I)
# Find each "DD <Month>" pair followed by "Car Trackday" / "Bike Trackday".
DATE_BLOCK_RE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:Car|Bike|Drift)\s*Trackday",
    re.I,
)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    seen = set()
    for vehicle, url in URLS.items():
        tree = await get_html_js(url, wait_selector="#tabcontent0")
        (DEBUG_DIR / f"llandow_{vehicle}.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

        pane = tree.css_first("#tabcontent0")
        if not pane:
            continue
        text = pane.text(separator=" ", strip=True)

        ym = YEAR_RE.search(text)
        year = int(ym.group(1)) if ym else date.today().year

        for m in DATE_BLOCK_RE.finditer(text):
            day = int(m.group(1))
            mon_name = m.group(2)
            try:
                event_date = datetime.strptime(f"{day} {mon_name} {year}", "%d %B %Y").date()
            except ValueError:
                continue

            key = (vehicle, event_date)
            if key in seen:
                continue
            seen.add(key)

            out.append(RawEvent(
                source=SOURCE_SLUG, organiser=ORGANISER,
                circuit_raw="Llandow", event_date=event_date, booking_url=url,
                title=f"{vehicle.title()} Trackday — Llandow",
                vehicle_type=vehicle, session="day",
                external_id=f"{vehicle}|{event_date}",
            ))
    return out
