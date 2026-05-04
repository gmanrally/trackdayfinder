"""Track Obsession — https://trackobsession.co.uk/product-category/all-events/

WooCommerce + custom Elementor template. Each event card is:
  <a class="product-shop78" href="...booking URL...">
    h3                      -> "Cadwell Park - Evening"
    h6                      -> "05/05/2026"  (DD/MM/YYYY)
    .product-price          -> "£119"
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "trackobsession"
ORGANISER = "Track Obsession"
LISTING_URL = "https://trackobsession.co.uk/product-category/all-events/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".product-shop78")
    (DEBUG_DIR / "trackobsession.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")
    out: list[RawEvent] = []
    for card in tree.css(".product-shop78"):
        ev = _parse(card)
        if ev:
            out.append(ev)
    return out


def _parse(card: Node) -> Optional[RawEvent]:
    href = card.attributes.get("href") or LISTING_URL
    title_node = card.css_first("h3")
    date_node = card.css_first("h6")
    if not title_node or not date_node:
        return None
    title = title_node.text(strip=True)
    m = DATE_RE.search(date_node.text(strip=True))
    if not m:
        return None
    try:
        event_date = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%d/%m/%Y").date()
    except ValueError:
        return None

    price_text = None
    price_node = card.css_first(".product-price")
    if price_node:
        pm = PRICE_RE.search(price_node.text(strip=True).replace(",", ""))
        if pm:
            price_text = f"£{pm.group(1)}"

    # Title pattern is "<Circuit> - <Session>". Strip session for canonical circuit.
    circuit_raw = title.split(" - ", 1)[0].strip()
    session = "day"
    low = title.lower()
    if "evening" in low or "(eve" in low:
        session = "evening"

    sku = href.rstrip("/").rsplit("/", 1)[-1]
    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=href,
        title=title, price_text=price_text,
        session=session, external_id=sku,
    )
