"""Castle Combe Circuit — https://castlecombecircuit.co.uk/

Circuit-direct trackdays (separate from MSV/Javelin/Goldtrack/OpenTrack
who hire the venue). Four WooCommerce shop pages — two car products
and two bike products — each carrying every date as a variant in a
`data-product_variations` JSON attribute on the variations form.

Each variant has:
  attributes['attribute_choose-date'] → 'Fri 12th June 2026'
  display_price                       → 190
  is_in_stock                         → True/False
  variation_id                        → 900386

Variants whose date attribute is 'Additional Driver', 'Add Passenger',
'Helmet Hire' etc. are non-date add-ons — skipped.
"""
from __future__ import annotations
import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html

SOURCE_SLUG = "castle_combe"
ORGANISER = "Castle Combe Circuit"
BASE_URL = "https://castlecombecircuit.co.uk"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# (vehicle, slug, optional title-hint).
PRODUCTS = [
    ("car",  "shop/car-track-day",                  None),
    ("car",  "shop/pistonheads-novice-car-track-day", "Novice"),
    ("bike", "shop/motorcycle-track-day",           None),
    ("bike", "shop/premium-motorcycle-track-day",   "Premium"),
]

# 'Fri 24 April 2026' / 'Fri 12th June 2026' / 'Thu 1st May 2026'
DATE_RE = re.compile(
    r"^\w{3,9}\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})$"
)
# Non-date variant labels we should skip.
SKIP_LABELS = ("driver", "passenger", "helmet", "voucher", "tuition",
               "insurance", "add ", "extra", "spectator")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    seen: set[str] = set()
    for vehicle, path, title_hint in PRODUCTS:
        url = f"{BASE_URL}/{path}/"
        try:
            tree = await get_html(url, timeout=25.0)
        except Exception:
            continue
        raw = tree.html or ""
        (DEBUG_DIR / f"castle_combe_{path.replace('/', '_')}.html").write_text(
            raw, encoding="utf-8", errors="ignore"
        )
        m = re.search(r'data-product_variations="([^"]+)"', raw)
        if not m:
            continue
        try:
            variants = json.loads(html.unescape(m.group(1)))
        except (json.JSONDecodeError, ValueError):
            continue
        for v in variants:
            ev = _build(v, vehicle, path, url, title_hint)
            if ev and ev.external_id not in seen:
                seen.add(ev.external_id)
                out.append(ev)
    return out


def _build(v: dict, vehicle: str, path: str, url: str,
           title_hint: Optional[str]) -> Optional[RawEvent]:
    attrs = v.get("attributes", {}) or {}
    label = (attrs.get("attribute_choose-date")
             or attrs.get("attribute_pa_choose-date") or "").strip()
    if not label:
        return None
    low = label.lower()
    if any(s in low for s in SKIP_LABELS):
        return None
    dm = DATE_RE.match(label)
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

    vid = v.get("variation_id")
    if not vid:
        return None
    sku = f"{path}|{vid}"
    price = v.get("display_price")
    in_stock = bool(v.get("is_in_stock"))

    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw="Castle Combe",
        event_date=event_date,
        booking_url=url,
        title=title_hint,
        price_text=f"£{float(price):.0f}" if price else None,
        currency="GBP",
        vehicle_type=vehicle,
        sold_out=not in_stock,
        session="day",
        external_id=sku,
        region="UK",
    )
