"""Slip and Grip Automotive — https://www.slipandgripautomotive.co.uk/shop/events/

WooCommerce shop. Each li.product:
  a.woocommerce-loop-product__link  -> booking URL
  .woocommerce-loop-product__title  -> "Open Pitlane Trackdays Castle Combe Circuit"
  .gsl-evt-date-date                -> "10/07/2026" (DD/MM/YYYY)
  .woocommerce-Price-amount         -> "£130.00"
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "slipandgrip"
ORGANISER = "Slip and Grip Automotive"
LISTING_URL = "https://www.slipandgripautomotive.co.uk/shop/events/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector="li.product")
    (DEBUG_DIR / "slipandgrip.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")
    out: list[RawEvent] = []
    for card in tree.css("li.product"):
        ev = _parse(card)
        if ev:
            out.append(ev)
    return out


def _parse(card: Node) -> Optional[RawEvent]:
    title_node = card.css_first(".woocommerce-loop-product__title")
    if not title_node:
        return None
    title = title_node.text(strip=True)
    # Filter out non-trackday events (cars & coffee meets etc.)
    if "trackday" not in title.lower() and "track day" not in title.lower():
        return None

    link = card.css_first("a.woocommerce-loop-product__link")
    href = (link.attributes.get("href") if link else None) or LISTING_URL

    date_node = card.css_first(".gsl-evt-date-date")
    if not date_node:
        return None
    m = DATE_RE.search(date_node.text(strip=True))
    if not m:
        return None
    try:
        event_date = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%d/%m/%Y").date()
    except ValueError:
        return None

    price_text = None
    price_node = card.css_first(".woocommerce-Price-amount")
    if price_node:
        pm = PRICE_RE.search(price_node.text(strip=True).replace(",", ""))
        if pm and float(pm.group(1)) > 0:
            price_text = f"£{pm.group(1)}"

    # Strip leading event-type words from title to extract circuit
    circuit_raw = re.sub(r"^(Classic and Retro|Open Pitlane|Open Pit Lane|Sessioned)\s+Trackday[s]?\s+", "", title, flags=re.I)
    circuit_raw = circuit_raw.strip() or title
    sku = href.rstrip("/").rsplit("/", 1)[-1]

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=href,
        title=title, price_text=price_text,
        session="day", external_id=sku,
    )
