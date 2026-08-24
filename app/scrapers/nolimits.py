"""No Limits Trackdays — https://www.nolimitstrackdays.com/uk-track-days

UK bike trackdays. The 2026-07 site redesign replaced /events-list.html
(.product-range groups) with a JS-rendered card list; the old track-page
URLs (/uk-tracks/donington.html?from=...) now 301 to the tracks index,
which is what broke deep-linking for over a month (scraper returned 0
events; stale July rows kept showing with dead links).

Each event is one <a class="uk-event-card" href="/donington-park-august-27-2026">
with the deep link right on the card:
  data-circuit          -> "Brands Hatch Indy"
  .card-date            -> "Tue 25 Aug 2026"
  .card-name            -> "Brands Hatch Indy - August 25, 2026"
  .card-desc            -> "4 Groups noise level 102db static."
  .card-price           -> "£159.00 / per person"
  .uk-group-chips .uk-chip{ available | limited-spaces | almost-sold-out | soldout }
                        -> per-group availability; sold out = every chip soldout
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
BASE_URL = "https://www.nolimitstrackdays.com"
LISTING_URL = f"{BASE_URL}/uk-track-days"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".uk-event-card")
    (DEBUG_DIR / "nolimits.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for card in tree.css(".uk-event-card"):
        ev = _parse(card)
        if ev:
            out.append(ev)
    return out


def _parse(card: Node) -> Optional[RawEvent]:
    href = (card.attributes.get("href") or "").strip()
    if not href:
        return None
    booking_url = href if href.startswith("http") else BASE_URL + href

    date_node = card.css_first(".card-date")
    if not date_node:
        return None
    try:
        event_date = datetime.strptime(date_node.text(strip=True), "%a %d %b %Y").date()
    except ValueError:
        return None

    circuit_raw = (card.attributes.get("data-circuit") or "").strip()
    if not circuit_raw:
        cnode = card.css_first(".card-circuit")
        circuit_raw = cnode.text(strip=True).lstrip("📍").strip() if cnode else ""
    if not circuit_raw:
        return None

    name_node = card.css_first(".card-name")
    title = name_node.text(strip=True) if name_node else circuit_raw

    desc_node = card.css_first(".card-desc")
    desc = desc_node.text(separator=" ", strip=True) if desc_node else None

    price_text = None
    price_node = card.css_first(".card-price")
    if price_node:
        pm = PRICE_RE.search(price_node.text(strip=True).replace(",", ""))
        if pm:
            price_text = f"£{pm.group(1)}"

    chips = card.css(".uk-group-chips .uk-chip")
    sold_out = bool(chips) and all("soldout" in (c.attributes.get("class") or "") for c in chips)
    low = (not sold_out) and any(
        ("almost-sold-out" in (c.attributes.get("class") or "")
         or "limited-spaces" in (c.attributes.get("class") or "")) for c in chips)

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=booking_url,
        title=title, price_text=price_text, noise_text=desc,
        notes=desc, vehicle_type="bike",
        sold_out=sold_out, spaces_left=0 if sold_out else None,
        stock_status="Sold Out" if sold_out else ("Low Stock" if low else None),
        session="evening" if "evening" in href.lower() else "day",
        external_id=href.strip("/"),
    )
