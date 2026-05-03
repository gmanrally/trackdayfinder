"""MOT Trackdays — https://mottrackdays.com/book-a-track-day-52-c.asp

EKM cart-based site. Each card is .aerial-product-item:
  .product-name a       -> "Croft Circuit - Friday 27th March 2026" + href
  .aerial-product-item_price -> "£250.00"
  p.stock-indicator     -> "Places Available" / "Sold Out" / similar
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "mot"
ORGANISER = "MOT Trackdays"
LISTING_URL = "https://mottrackdays.com/book-a-track-day-52-c.asp"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")
ID_RE = re.compile(r"-(\d+)-p\.asp$")
TITLE_DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".aerial-product-item")
    (DEBUG_DIR / "mot.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for card in tree.css(".aerial-product-item"):
        ev = _parse(card)
        if ev:
            out.append(ev)
    return out


def _parse(card: Node) -> Optional[RawEvent]:
    a = card.css_first(".product-name a")
    if not a:
        return None
    title = a.text(strip=True)
    href = a.attributes.get("href", "")
    if not href.startswith("http"):
        href = "https://mottrackdays.com/" + href.lstrip("/")
    sku_m = ID_RE.search(href)
    sku = sku_m.group(1) if sku_m else None

    dt_m = TITLE_DATE_RE.search(title)
    if not dt_m:
        return None
    try:
        event_date = datetime.strptime(f"{dt_m.group(1)} {dt_m.group(2)} {dt_m.group(3)}", "%d %B %Y").date()
    except ValueError:
        return None

    circuit_raw = title.split(" - ", 1)[0].strip()

    price_node = card.css_first(".aerial-product-item_price")
    price_text = None
    if price_node:
        m = PRICE_RE.search(price_node.text(strip=True).replace(",", ""))
        if m:
            price_text = f"£{m.group(1)}"

    stock_node = card.css_first(".stock-indicator")
    stock_text = stock_node.text(strip=True) if stock_node else ""
    low = stock_text.lower()
    sold_out = "sold out" in low or "out of stock" in low
    spaces_left = 0 if sold_out else None
    stock_status = stock_text if sold_out or any(k in low for k in ("low", "limited", "few", "almost")) else None

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=href,
        title=title, price_text=price_text,
        sold_out=sold_out, spaces_left=spaces_left, stock_status=stock_status,
        session="day", external_id=sku,
    )
