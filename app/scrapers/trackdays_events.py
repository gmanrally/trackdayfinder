"""Trackdays.events — https://trackdays.events/en/calendar-4/

Global European calendar aggregator. The page contains one <table class="events">
per month, each preceded by an <h2>Month YYYY</h2>. Each row:
  td 0  date span "Mon 4 May" (no year — taken from preceding h2)
  td 1  country/track "F - Fontenay-le-Comte (circuits de Vendée)"
  td 2  organiser
  td 3  trackday type "open pitlane" / "sessioned"
  td 4  note
  td 5  link to organiser website
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node, HTMLParser
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "trackdays_events"
ORGANISER = "Trackdays.events"
LISTING_URL = "https://trackdays.events/en/calendar-4/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(?:[A-Za-z]{3,9}\s+)?(\d{1,2})\s+([A-Za-z]+)")
MONTH_HEADER_RE = re.compile(r"([A-Za-z]+)\s+(\d{4})")
COUNTRY_PREFIX_RE = re.compile(r"^([A-Z]{1,3})\s*[-–—]\s*", re.UNICODE)
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".mydate")
    (DEBUG_DIR / "trackdays_events.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    today = date.today()
    current_month: Optional[int] = None
    current_year: Optional[int] = None
    # Walk h2 + tables in document order
    for node in tree.css("h2, table.events"):
        if node.tag == "h2":
            m = MONTH_HEADER_RE.search(node.text(strip=True))
            if m and m.group(1) in MONTHS:
                current_month = MONTHS[m.group(1)]
                current_year = int(m.group(2))
            continue
        # node is table.events
        if current_month is None or current_year is None:
            continue
        for tr in node.css("tbody tr"):
            ev = _parse_row(tr, current_year, current_month)
            if ev and ev.event_date >= today:
                out.append(ev)
    return out


def _parse_row(tr: Node, year: int, month: int) -> Optional[RawEvent]:
    cells = tr.css("td")
    if len(cells) < 5:
        return None

    date_text = cells[0].text(strip=True)
    dm = DATE_RE.search(date_text)
    if not dm:
        return None
    try:
        event_date = date(year, month, int(dm.group(1)))
    except ValueError:
        return None

    country_track = cells[1].text(separator=" ", strip=True).strip()
    country_track = re.sub(r"\s+", " ", country_track)
    cm = COUNTRY_PREFIX_RE.match(country_track)
    circuit_raw = country_track[cm.end():].strip() if cm else country_track

    organiser_text = cells[2].text(separator=" ", strip=True) or "Trackdays.events"
    fmt_text = cells[3].text(separator=" ", strip=True)
    note = cells[4].text(separator=" ", strip=True)
    if note in ("-", ""):
        note = None

    # The booking link: any <a href> in the row
    booking_url = LISTING_URL
    for a in tr.css("a"):
        href = a.attributes.get("href", "")
        if href.startswith("http"):
            booking_url = href
            break

    title = f"{fmt_text} — {organiser_text}".strip(" —") if fmt_text else organiser_text

    sku = f"{circuit_raw[:30]}|{event_date}|{organiser_text[:30]}"
    return RawEvent(
        source=SOURCE_SLUG, organiser=organiser_text or ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=booking_url,
        title=title, notes=note,
        currency="EUR", region="EU",
        session="day", external_id=sku,
    )
