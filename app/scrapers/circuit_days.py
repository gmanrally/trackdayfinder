"""Circuit Days — https://circuit-days.co.uk/schedule

Each .event card:
  .event-title  -> "Anglesey GP"
  .event-price  -> "£249"
  .event-date   -> "Mon 04 May, 2026"
  .event-desc   -> "Open pit lane track day"
  a[itemprop=url] -> Details / booking link
  a.sold        -> presence = sold out
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "circuit_days"
ORGANISER = "Circuit Days"
LISTING_URL = "https://circuit-days.co.uk/schedule"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"([A-Za-z]{3})\s+(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})")
PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".event")
    (DEBUG_DIR / "circuit_days.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for card in tree.css(".event"):
        ev = _parse(card)
        if ev:
            out.append(ev)
    return out


def _parse(card) -> Optional[RawEvent]:
    title_node = card.css_first(".event-title")
    date_node = card.css_first(".event-date")
    if not title_node or not date_node:
        return None
    circuit = title_node.text(strip=True)

    m = DATE_RE.search(date_node.text(strip=True))
    if not m:
        return None
    try:
        event_date = datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", "%d %B %Y").date()
    except ValueError:
        try:
            event_date = datetime.strptime(f"{m.group(2)} {m.group(3)[:3]} {m.group(4)}", "%d %b %Y").date()
        except ValueError:
            return None

    href = LISTING_URL
    sku = None
    for a in card.css("a"):
        if (a.attributes.get("itemprop") or "") == "url":
            href = a.attributes.get("href") or LISTING_URL
            sku = href.rsplit("/", 1)[-1]
            break

    desc = (card.css_first(".event-desc").text(strip=True) if card.css_first(".event-desc") else "") or None

    price_node = card.css_first(".event-price")
    price_text = None
    if price_node:
        m2 = PRICE_RE.search(price_node.text(strip=True).replace(",", ""))
        if m2:
            price_text = f"£{m2.group(1)}"

    sold_out = bool(card.css_first("a.sold"))
    stock_status = "Sold Out" if sold_out else None

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit, event_date=event_date, booking_url=href,
        title=desc or circuit, price_text=price_text, notes=desc,
        sold_out=sold_out, stock_status=stock_status,
        spaces_left=0 if sold_out else None,
        session="day", external_id=sku,
    )
