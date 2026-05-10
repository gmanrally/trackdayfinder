"""Curbstone Track Events — https://www.curbstone.net/

Belgian operator running premium track + test days at Spa, Paul Ricard,
Monza, Nürburgring, Barcelona, Hockenheim, Red Bull Ring. SSR Odoo site.

Listing pages: /event/page/<n>?date=upcoming  (12 events/page)
Card title format: '<SERIES> I <TYPE> I <DATE>' e.g.
  'CIRCUIT PAUL RICARD I TRACK & TEST DAY I 26-27 MAY 2026'
  'SPA 2H I SESSION 03 I 01 JUNE 2026'
Date may be a single day or a 'D-D MONTH YYYY' range — we use start date.

We don't fetch each event detail page for price (that'd be 60+ requests
per scrape); price stays None and the existing snapshot system can fill
it in later if we add an opt-in detail fetch.
"""
from __future__ import annotations
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from selectolax.parser import HTMLParser
from ._base import RawEvent, get_html

SOURCE_SLUG = "curbstone"
ORGANISER = "Curbstone Track Events"
BASE_URL = "https://www.curbstone.net"
LIST_URL = BASE_URL + "/event/page/{page}?date=upcoming"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"
MAX_PAGES = 12  # safety cap

# Map Curbstone's series labels to canonical CIRCUIT_COORDS names.
SERIES_TO_CIRCUIT = {
    "AZUR":              "Paul Ricard",   # Curbstone's Paul Ricard 2H series
    "AZUR 2H":           "Paul Ricard",
    "CIRCUIT PAUL RICARD": "Paul Ricard",
    "SPA":               "Spa-Francorchamps",
    "SPA 2H":            "Spa-Francorchamps",
    "SPA 2H - ALPINE ONLY": "Spa-Francorchamps",
    "MONZA":             "Monza",
    "MONZA 2H":          "Monza",
    "NORDSCHLEIFE":      "Nürburgring (Nordschleife)",
    "NURBURGRING GP":    "Nürburgring (Grand Prix)",
    "NÜRBURGRING GP":    "Nürburgring (Grand Prix)",
    "NURBURGRING SPRINT": "Nürburgring (Grand Prix)",
    "NÜRBURGRING SPRINT": "Nürburgring (Grand Prix)",
    "HOCKENHEIM":        "Hockenheim",
    "BARCELONA":         "Barcelona-Catalunya",
    "RED BULL RING":     "Red Bull Ring",
    # Multi-circuit tours / non-track events — skipped in _parse_card.
}
SKIP_SERIES = {"MOTOR VALLEY TOUR", "WATCH VALLEY TOUR", "ZOUTE GT TOUR BY CURBSTONE",
               "CAR HANDLING TRAINING"}

DATE_RE = re.compile(
    r"(\d{1,2})(?:\s*-\s*\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})"
)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    seen_ids: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        tree = await get_html(LIST_URL.format(page=page))
        html = tree.html or ""
        # Walk the raw HTML so we can pair each <h4 card-title> with the next
        # /event/<slug>-<id>/register link that follows it (the card layout
        # has many other elements between the title and the booking button,
        # so DOM-walking up to find an ancestor <a> doesn't work — there
        # isn't one).
        cards = re.findall(
            r'<h4[^>]*class="[^"]*card-title[^"]*"[^>]*>([^<]+)</h4>'
            r'.*?(/event/[a-z0-9-]+-(\d+)/register)',
            html, re.DOTALL,
        )
        if not cards:
            break
        for raw_title, href, sku in cards:
            if sku in seen_ids: continue
            ev = _build_event(raw_title, href, sku, html)
            if ev:
                seen_ids.add(sku)
                out.append(ev)
        if page == 1:
            (DEBUG_DIR / "curbstone.html").write_text(html, encoding="utf-8", errors="ignore")
    return out


def _build_event(raw_title: str, href: str, sku: str, page_html: str) -> Optional[RawEvent]:
    title = raw_title.replace("&amp;", "&").replace("\xa0", " ").strip()
    booking_url = BASE_URL + href

    # Title format: '<SERIES> I <TYPE> I <DATE>'  (Capital "I" as separator)
    parts = [p.strip() for p in re.split(r"\s+I\s+", title)]
    if len(parts) < 2:
        return None
    series = parts[0].upper()
    if series in SKIP_SERIES:
        return None
    circuit = SERIES_TO_CIRCUIT.get(series)
    if not circuit:
        return None  # unknown series — skip rather than guess
    date_part = parts[-1]

    dm = DATE_RE.search(date_part)
    if not dm:
        return None
    day, month_s, year_s = dm.group(1), dm.group(2), dm.group(3)
    try:
        event_date = datetime.strptime(f"{day} {month_s} {year_s}", "%d %B %Y").date()
    except ValueError:
        try:
            event_date = datetime.strptime(f"{day} {month_s[:3]} {year_s}", "%d %b %Y").date()
        except ValueError:
            return None
    if event_date < date.today():
        return None

    # Sold-out + noise: scan the slice of page HTML between this card's
    # title and its booking link (everything in the card lives in between).
    title_idx = page_html.find(raw_title)
    href_idx = page_html.find(href, title_idx) if title_idx != -1 else -1
    sold_out = False
    noise_db: Optional[int] = None
    if title_idx != -1 and href_idx != -1:
        slice_ = page_html[title_idx:href_idx]
        if re.search(r"sold\s*out", slice_, re.I):
            sold_out = True
        nm = re.search(r"(\d{2,3})\s*dB", slice_)
        if nm:
            noise_db = int(nm.group(1))

    is_2h = "2H" in parts[1].upper() if len(parts) >= 3 else False
    title_clean = " - ".join(parts[1:-1]) if len(parts) >= 3 else None

    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=booking_url,
        title=title_clean,
        currency="EUR",
        sold_out=sold_out,
        noise_text=f"{noise_db} dB" if noise_db else None,
        session=("am_pm" if is_2h else "day"),
        external_id=sku,
        region="EU",
    )
