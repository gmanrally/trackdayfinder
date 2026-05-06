"""Trackday Solutions — https://www.trackday-solutions.co.uk/

Wix-hosted store; the /trackdays page is server-rendered with the product
catalogue embedded in the HTML as JSON. Each product object follows the
field order: price, urlPart, name, isInStock. Anchor on urlPart and read
the surrounding fields.

Product `name` format: "CIRCUIT - <ordinal> <Month> <Year> - <Title>"
e.g. "BLYTON PARK - 5th July 2026 - Open Pit Trackday"
"""
from __future__ import annotations
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html, UA  # get_html returns HTMLParser; we want raw text, fetch separately
import httpx

SOURCE_SLUG = "trackday_solutions"
ORGANISER = "Trackday Solutions"
LIST_URL = "https://www.trackday-solutions.co.uk/trackdays"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# Map shouty Wix circuit names to the canonical names used in CIRCUIT_COORDS.
CIRCUIT_NAME_MAP = {
    "BLYTON PARK":  "Blyton Park",
    "CADWELL":      "Cadwell Park",
    "CADWELL PARK": "Cadwell Park",
    "MALLORY":      "Mallory Park",
    "MALLORY PARK": "Mallory Park",
    "THRUXTON":     "Thruxton",
    "BRANDS HATCH": "Brands Hatch",
    "DONINGTON":    "Donington Park",
    "DONINGTON PARK": "Donington Park",
    "OULTON PARK":  "Oulton Park",
    "SNETTERTON":   "Snetterton",
    "SILVERSTONE":  "Silverstone",
    "ANGLESEY":     "Anglesey",
    "CASTLE COMBE": "Castle Combe",
    "CROFT":        "Croft",
    "PEMBREY":      "Pembrey",
}

# "5th July 2026" / "1st June 2026" / "23rd September 2026" / "12th December 2026"
DATE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})"
)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True, timeout=20.0) as c:
        r = await c.get(LIST_URL)
        r.raise_for_status()
        html = r.text
    (DEBUG_DIR / "trackday_solutions.html").write_text(html, encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    seen: set[str] = set()
    # Anchor on urlPart so each product is processed once. Wix encodes the
    # price slightly before urlPart, name + isInStock slightly after.
    for m in re.finditer(r'"urlPart":"(\d{6})"', html):
        sku = m.group(1)
        if sku in seen:
            continue
        seen.add(sku)

        back = html[max(0, m.start() - 500):m.start()]
        fwd = html[m.end(): m.end() + 1500]

        # Wix product field order is: price, ..., sku, isInStock, urlPart,
        # formattedPrice, ..., name. So price + isInStock are in `back`
        # (take the last occurrence — closest to this product), name in `fwd`.
        prices = re.findall(r'"price":(\d+(?:\.\d+)?)', back)
        stocks = re.findall(r'"isInStock":(true|false)', back)
        name_m = re.search(r'"name":"([^"]+)"', fwd)

        if not name_m:
            continue
        ev = _build_event(sku, name_m.group(1),
                          float(prices[-1]) if prices else None,
                          (stocks[-1] == "true") if stocks else True)
        if ev:
            out.append(ev)
    return out


def _build_event(sku: str, name: str, price: Optional[float], in_stock: bool) -> Optional[RawEvent]:
    # Parse "CIRCUIT - <date> - <title>"
    parts = [p.strip() for p in name.split(" - ")]
    if len(parts) < 2:
        return None
    circuit_raw = parts[0]
    date_part = parts[1] if len(parts) > 1 else ""
    title = " - ".join(parts[2:]) if len(parts) > 2 else None

    m = DATE_RE.search(date_part)
    if not m:
        return None
    day_s, month_s, year_s = m.group(1), m.group(2), m.group(3)
    try:
        event_date = datetime.strptime(f"{day_s} {month_s} {year_s}", "%d %B %Y").date()
    except ValueError:
        try:
            event_date = datetime.strptime(f"{day_s} {month_s[:3]} {year_s}", "%d %b %Y").date()
        except ValueError:
            return None
    if event_date < date.today():
        return None

    circuit = CIRCUIT_NAME_MAP.get(circuit_raw.upper(), circuit_raw.title())
    booking_url = f"https://www.trackday-solutions.co.uk/product-page/{sku}"

    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=booking_url,
        title=title,
        price_text=f"£{price:.0f}" if price else None,
        currency="GBP",
        sold_out=not in_stock,
        session="day",
        external_id=sku,
        region="UK",
    )
