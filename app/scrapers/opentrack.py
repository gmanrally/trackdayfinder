"""OpenTrack — https://opentrack.co.uk/view-dates

Each event is a <tr id="event_row_NNN" data-filter-day-eve="d|e">:
  td.date     -> "Mon 11th May" (year missing — read from data-share-title)
  td.dayeve   -> "All Day 07:30 - 17:00" / "Evening ..."
  td.circuit  -> circuit name (text precedes "Important Details ...")
  td.noise    -> "No Limit drive by 90 db static"
  td.price    -> "£ 199"
  td.book-btn -> "BOOK"  (or td.sold-out -> "SOLD OUT")

Booking URL: https://opentrack.co.uk/view-dates?book-event=NNN
The data-share-title attribute on share buttons holds full date as DD-MM-YYYY.
"""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "opentrack"
ORGANISER = "OpenTrack"
LISTING_URL = "https://opentrack.co.uk/view-dates"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

SHARE_DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")
PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")
EVENT_ID_RE = re.compile(r"event_row_(\d+)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector="tr[id^=event_row_]")
    (DEBUG_DIR / "opentrack.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for row in tree.css("tr[id^=event_row_]"):
        ev = _parse(row)
        if ev:
            out.append(ev)
    return out


def _parse(row: Node) -> Optional[RawEvent]:
    rid = row.attributes.get("id") or ""
    m = EVENT_ID_RE.search(rid)
    if not m:
        return None
    event_id = m.group(1)

    # Pull DD-MM-YYYY out of any data-share-title in the row
    event_date = None
    for el in row.css("[data-share-title]"):
        t = el.attributes.get("data-share-title") or ""
        dm = SHARE_DATE_RE.search(t)
        if dm:
            try:
                event_date = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
                break
            except ValueError:
                pass
    if not event_date:
        return None

    circuit_td = row.css_first("td.circuit")
    if not circuit_td:
        return None
    # circuit name is the leading text node, before the first inner button
    raw_lead = ""
    for child in circuit_td.iter(include_text=True):
        if child.tag == "-text":
            raw_lead = (child.text() or "").strip()
            if raw_lead:
                break
    circuit = raw_lead or circuit_td.text(strip=True).split("Important")[0].strip()

    dayeve_attr = (row.attributes.get("data-filter-day-eve") or "").lower()
    session = "evening" if dayeve_attr == "e" else "day"
    dayeve_td = row.css_first("td.dayeve")
    dayeve_text = dayeve_td.text(separator=" ", strip=True) if dayeve_td else ""

    noise_td = row.css_first("td.noise")
    noise_text = noise_td.text(separator=" ", strip=True) if noise_td else None

    price_td = row.css_first("td.price")
    price_text = None
    if price_td:
        pm = PRICE_RE.search(price_td.text(strip=True).replace(",", "").replace(" ", ""))
        if pm:
            price_text = f"£{pm.group(1)}"

    sold_out = row.css_first("td.sold-out") is not None
    stock_status = "Sold Out" if sold_out else None
    spaces_left = 0 if sold_out else None
    booking_url = f"https://opentrack.co.uk/view-dates?{'view-event' if sold_out else 'book-event'}={event_id}"

    title = f"{circuit} — {dayeve_text}".strip(" —") if dayeve_text else circuit

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit, event_date=event_date, booking_url=booking_url,
        title=title, price_text=price_text, noise_text=noise_text,
        sold_out=sold_out, spaces_left=spaces_left, stock_status=stock_status,
        session=session, external_id=event_id,
    )
