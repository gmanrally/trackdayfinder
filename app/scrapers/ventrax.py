"""Ventrax Motorsport — https://ventraxmotorsportshop.com/

Shopify store selling trackday tickets as products with product_type
"Event Ticket". We read the standard Shopify /products.json feed (reliable,
no HTML parsing) and keep the driver tickets, dropping passenger/spectator
ones. Date + circuit are embedded in the product title, e.g.
  "VENTRAX & STATUS ANGLESEY TRACK DAY – 20TH AUGUST 2026"
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import httpx
from ._base import RawEvent, UA

SOURCE_SLUG = "ventrax"
ORGANISER = "Ventrax Motorsport"
PRODUCTS_URL = "https://ventraxmotorsportshop.com/products.json?limit=250"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# Circuit keywords → canonical CIRCUIT_COORDS names.
CIRCUIT_KEYWORDS = [
    ("anglesey",     "Anglesey"),
    ("donington",    "Donington Park"),
    ("brands",       "Brands Hatch"),
    ("silverstone",  "Silverstone"),
    ("oulton",       "Oulton Park"),
    ("snetterton",   "Snetterton"),
    ("cadwell",      "Cadwell Park"),
    ("croft",        "Croft"),
    ("castle combe", "Castle Combe"),
    ("blyton",       "Blyton Park"),
    ("mallory",      "Mallory Park"),
    ("pembrey",      "Pembrey"),
    ("knockhill",    "Knockhill"),
    ("thruxton",     "Thruxton"),
    ("bedford",      "Bedford Autodrome"),
    ("lydden",       "Lydden Hill"),
    ("three sisters","Three Sisters"),
]

# Non-driver tickets to skip.
SKIP_RE = re.compile(r"passanger|passenger|spectator|voucher|gift|merch", re.I)
DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", re.I)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=20.0,
                                 follow_redirects=True) as c:
        r = await c.get(PRODUCTS_URL)
        r.raise_for_status()
        data = r.json()
    (DEBUG_DIR / "ventrax.json").write_text(r.text, encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    seen: set[str] = set()
    for p in data.get("products", []):
        if (p.get("product_type") or "").lower() != "event ticket":
            continue
        title = (p.get("title") or "").strip()
        if not title or SKIP_RE.search(title):
            continue
        ev = _build(p, title)
        if ev and ev.external_id not in seen:
            seen.add(ev.external_id)
            out.append(ev)
    return out


def _build(p: dict, title: str) -> Optional[RawEvent]:
    dm = DATE_RE.search(title)
    if not dm:
        return None
    day_s, month_s, year_s = dm.group(1), dm.group(2), dm.group(3)
    try:
        event_date = datetime.strptime(f"{day_s} {month_s} {year_s}", "%d %B %Y").date()
    except ValueError:
        try:
            event_date = datetime.strptime(f"{day_s} {month_s[:3]} {year_s}", "%d %b %Y").date()
        except ValueError:
            return None
    if event_date < date.today():
        return None

    low = title.lower()
    circuit = None
    for kw, name in CIRCUIT_KEYWORDS:
        if kw in low:
            circuit = name
            break
    if not circuit:
        return None  # unknown circuit — skip rather than guess

    handle = p.get("handle", "")
    booking_url = f"https://ventraxmotorsportshop.com/products/{handle}"
    variants = p.get("variants") or [{}]
    v0 = variants[0]
    price = v0.get("price")
    available = any(v.get("available") for v in variants)

    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=booking_url,
        title="Track Day",
        price_text=f"£{float(price):.0f}" if price else None,
        currency="GBP",
        sold_out=not available,
        session="day",
        external_id=str(p.get("id") or handle),
        region="UK",
    )
