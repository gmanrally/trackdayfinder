"""Motorsport Events — https://www.motorsport-events.com/collections/track-days

Shopify. Each row is <tr class="sortRow" data-sortdate="YYYYMMDD">:
  td 0 -> short date "Sat 13th June" (we use data-sortdate instead)
  td 1 -> .title text "13 June 2026: Castle Combe track day"
  td 2 -> .money "£249.00"
  td 3 -> "View / Book Now" link to /collections/track-days/products/<slug>
"""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "msevents"
ORGANISER = "Motorsport Events"
LISTING_URL = "https://www.motorsport-events.com/collections/track-days"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")
TITLE_CIRCUIT_RE = re.compile(r":\s*([A-Za-z][A-Za-z\s]+?)\s+track\s+day", re.I)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".sortRow")
    (DEBUG_DIR / "msevents.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for row in tree.css(".sortRow"):
        ev = _parse(row)
        if ev:
            out.append(ev)
    return out


def _parse(row: Node) -> Optional[RawEvent]:
    sd = row.attributes.get("data-sortdate", "")
    if not (len(sd) == 8 and sd.isdigit()):
        return None
    try:
        event_date = date(int(sd[:4]), int(sd[4:6]), int(sd[6:8]))
    except ValueError:
        return None

    title_node = row.css_first(".title")
    title = title_node.text(strip=True) if title_node else ""
    if "voucher" in title.lower() or "gift" in title.lower():
        return None

    circuit_raw = title
    cm = TITLE_CIRCUIT_RE.search(title)
    if cm:
        circuit_raw = cm.group(1).strip()

    money = row.css_first(".money")
    price_text = None
    if money:
        m = PRICE_RE.search(money.text(strip=True).replace(",", ""))
        if m:
            price_text = f"£{m.group(1)}"

    book = None
    for a in row.css("a"):
        h = a.attributes.get("href", "")
        if "/products/" in h:
            book = h
            break
    if not book:
        return None
    if book.startswith("/"):
        book = "https://www.motorsport-events.com" + book
    sku = book.rstrip("/").rsplit("/", 1)[-1]

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=book,
        title=title, price_text=price_text,
        session="day", external_id=sku,
    )
