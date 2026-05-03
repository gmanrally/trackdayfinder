"""No Limits Trackdays — https://www.nolimitstrackdays.com/events-list.html

UK-only bike trackdays. Each .product-range is a date group:
  .date-container .date  -> "Monday - 04/05/2026"
  .product-list .product -> one per circuit on that date, with:
      .track-name        -> "Donington Park"
      .name              -> "Standard Track Day"
      .description       -> "3 Groups noise level Quiet 98db."
      .price             -> "£239.00"
      .actions a         -> book URL
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "nolimits"
ORGANISER = "No Limits Trackdays"
LISTING_URL = "https://www.nolimitstrackdays.com/events-list.html/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".product-range")
    (DEBUG_DIR / "nolimits.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for group in tree.css(".product-range"):
        date_text = group.css_first(".date").text(strip=True) if group.css_first(".date") else ""
        m = DATE_RE.search(date_text)
        if not m:
            continue
        try:
            event_date = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%d/%m/%Y").date()
        except ValueError:
            continue
        for prod in group.css(".product"):
            ev = _parse(prod, event_date)
            if ev:
                out.append(ev)
    return out


def _parse(prod: Node, event_date) -> Optional[RawEvent]:
    track = prod.css_first(".track-name")
    if not track:
        return None
    circuit_raw = track.text(strip=True)

    name_node = prod.css_first(".name")
    title = name_node.text(strip=True) if name_node else circuit_raw

    desc_node = prod.css_first(".description")
    desc = desc_node.text(separator=" ", strip=True) if desc_node else None

    price_node = prod.css_first(".price")
    price_text = None
    if price_node:
        pm = PRICE_RE.search(price_node.text(strip=True).replace(",", ""))
        if pm:
            price_text = f"£{pm.group(1)}"

    book = prod.css_first(".actions a")
    href = book.attributes.get("href", LISTING_URL) if book else LISTING_URL

    sold_out = bool(prod.css_first(".sold-out, .out-of-stock"))
    sku = None
    if href and "from=" in href:
        sku = href.split("from=")[-1].split("&")[0]

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=href,
        title=f"{title} — {circuit_raw}", price_text=price_text, noise_text=desc,
        notes=desc, vehicle_type="bike",
        sold_out=sold_out, spaces_left=0 if sold_out else None,
        stock_status="Sold Out" if sold_out else None,
        session="day", external_id=f"{circuit_raw}|{sku}" if sku else f"{circuit_raw}|{event_date}",
    )
