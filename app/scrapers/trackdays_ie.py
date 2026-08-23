"""Trackdays.ie — Mondello Park's official trackday partner (Ireland).

Shopify store, but structured differently from ventrax: one product per
EVENT TYPE with the dates in the VARIANTS ("September 4th. Friday / No /
No Extra Drivers"), except "Road Trips" (multi-day UK packages) which
carry a date range in the product title. The store also sells detailing
merch, gift cards and €3.5k+ track-car-hire — all skipped.

This is the scrapeable route to Mondello Park events: the circuit's own
site books through a Checkfront widget we can't reliably scrape (see the
note in circuit_coords.py).
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import httpx
from ._base import RawEvent, UA

SOURCE_SLUG = "trackdays_ie"
ORGANISER = "Trackdays.ie"
PRODUCTS_URL = "https://trackdays.ie/products.json?limit=250"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# Road-trip products name real UK circuits in the title.
CIRCUIT_KEYWORDS = [
    ("oulton",    "Oulton Park"),
    ("donington", "Donington Park"),
    ("anglesey",  "Anglesey"),
    ("mondello",  "Mondello Park"),
]

# Add-on products share the 'track days' tag but aren't trackday entries.
SKIP_RE = re.compile(r"media pack|passenger|extra driver|voucher|gift card", re.I)

# "September 4th" (variant style) — ordinal suffix required so the day can't
# eat the year out of "March 2026".
MONTH_FIRST = re.compile(r"\b([A-Za-z]{3,})\s+(\d{1,2})(?:st|nd|rd|th)\b", re.I)
# "22nd & 23rd March" / "28th - 30th June" (title style) — a day range
# collapses to its first day.
DAY_FIRST = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s*[&\-–]\s*\d{1,2}(?:st|nd|rd|th)?)?\s+([A-Za-z]{3,})\b", re.I)
YEAR_RE = re.compile(r"\b(20\d{2})\b")
WEEKDAY_RE = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}


def _day_month(text: str):
    """First (day, month) pair whose month word really is a month."""
    for m in MONTH_FIRST.finditer(text):
        try:
            return int(m.group(2)), datetime.strptime(m.group(1)[:3], "%b").month
        except ValueError:
            continue
    for m in DAY_FIRST.finditer(text):
        try:
            return int(m.group(1)), datetime.strptime(m.group(2)[:3], "%b").month
        except ValueError:
            continue
    return None


def _parse_date(text: str) -> Optional[date]:
    """Parse 'September 4th. Friday' / '22nd & 23rd March 2026' style dates.
    Only upcoming dates are returned. Shopify keeps stale past variants
    around, so a missing year is inferred cautiously: the named weekday
    must match when present (a bumped year rarely lands on the same
    weekday), and undated-far-future guesses (>300 days) are dropped."""
    dm = _day_month(text)
    if not dm:
        return None
    day, month = dm
    today = date.today()
    ym = YEAR_RE.search(text)
    if ym:
        try:
            d = date(int(ym.group(1)), month, day)
        except ValueError:
            return None
        return d if d >= today else None
    wd = WEEKDAY_RE.search(text)
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d < today:
            continue
        if wd and d.weekday() != WEEKDAYS[wd.group(1).lower()]:
            continue
        if not wd and (d - today).days > 300:
            continue
        return d
    return None


def _circuit_from(text: str) -> Optional[str]:
    low = text.lower()
    for kw, name in CIRCUIT_KEYWORDS:
        if kw in low:
            return name
    return None


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=20.0,
                                 follow_redirects=True) as c:
        r = await c.get(PRODUCTS_URL)
        r.raise_for_status()
        data = r.json()
    (DEBUG_DIR / "trackdays_ie.json").write_text(r.text, encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for p in data.get("products", []):
        tags = {t.lower() for t in (p.get("tags") or [])}
        is_trackday = ((p.get("product_type") or "").lower() == "trackday"
                       or "track days" in tags)
        if not is_trackday or "track car hire" in tags:
            continue
        title = (p.get("title") or "").strip()
        if not title or SKIP_RE.search(title):
            continue
        if "road trips" in tags or "roadtrip" in tags:
            ev = _build_road_trip(p, title)
            if ev:
                out.append(ev)
        else:
            out.extend(_build_from_variants(p, title))
    return out


def _build_road_trip(p: dict, title: str) -> Optional[RawEvent]:
    """Multi-day UK package, date range in the title. One row on the first
    day at the first named circuit; the title tells the full story."""
    event_date = _parse_date(title)
    circuit = _circuit_from(title)
    if not event_date or not circuit or event_date < date.today():
        return None
    variants = p.get("variants") or []
    prices = [float(v["price"]) for v in variants if v.get("price")]
    available = any(v.get("available") for v in variants)
    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=f"https://trackdays.ie/products/{p.get('handle', '')}",
        title=re.sub(r"\s*-\s*SOLD OUT\s*$", "", title, flags=re.I),
        price_text=f"€{min(prices):.0f}" if prices else None,
        currency="EUR",
        sold_out=not available or "sold out" in title.lower(),
        session="day",
        is_package=True,
        external_id=str(p.get("id") or p.get("handle")),
        region="UK",
    )


def _build_from_variants(p: dict, title: str) -> list[RawEvent]:
    """Mondello products: each variant is 'date / <options...>'. Group the
    variants by (date, session) and emit one event per group, priced from
    the cheapest variant, sold out only when every variant in the group is."""
    circuit = _circuit_from(title) or "Mondello Park"
    is_bundle = "bundle" in title.lower()
    groups: dict[tuple, dict] = {}
    for v in p.get("variants") or []:
        vt = (v.get("title") or "").strip()
        parts = [s.strip() for s in vt.split("/")]
        event_date = _parse_date(parts[0])
        if not event_date or event_date < date.today():
            continue
        session = "day"
        for part in parts[1:]:
            pl = part.lower()
            if pl == "morning":
                session = "am"
            elif pl == "afternoon":
                session = "pm"
        g = groups.setdefault((event_date, session), {"prices": [], "avail": False})
        if v.get("price"):
            g["prices"].append(float(v["price"]))
        g["avail"] = g["avail"] or bool(v.get("available"))

    out = []
    for (event_date, session), g in sorted(groups.items()):
        out.append(RawEvent(
            source=SOURCE_SLUG,
            organiser=ORGANISER,
            circuit_raw=circuit,
            event_date=event_date,
            booking_url=f"https://trackdays.ie/products/{p.get('handle', '')}",
            title=title.rstrip("."),
            price_text=f"€{min(g['prices']):.0f}" if g["prices"] else None,
            currency="EUR",
            sold_out=not g["avail"],
            session=session,
            is_package=is_bundle,
            external_id=f"{p.get('id')}-{event_date.isoformat()}-{session}",
            region="UK",
        ))
    return out
