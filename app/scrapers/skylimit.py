"""Skylimit Events — https://skylimitevents.com/

Belgian operator running trackdays primarily at Zolder (home) plus Mettet,
Spa-Francorchamps, Zandvoort, Assen, Meppen, Nürburgring (GP & Nordschleife),
Le Mans, Red Bull Ring. SSR Odoo site; same shape as Curbstone.

URL slug pattern: <event-type>-<circuit-tokens>-DD-MM-YYYY-<id>
We only ingest events whose slug embeds a date — drift shows / VR cup /
generic event pages without a date are skipped.
"""
from __future__ import annotations
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html

SOURCE_SLUG = "skylimit"
ORGANISER = "Skylimit Events"
BASE_URL = "https://skylimitevents.com"
LIST_URL = BASE_URL + "/en/event/page/{page}"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"
MAX_PAGES = 12

# Circuit-token clusters in slugs → canonical names. Longest match wins.
CIRCUIT_HINTS = [
    ("nurburgring-nordschleife", "Nürburgring (Nordschleife)"),
    ("nurburgring-gp-track",      "Nürburgring (Grand Prix)"),
    ("spa-francorchamps",         "Spa-Francorchamps"),
    ("red-bull-ring",             "Red Bull Ring"),
    ("le-mans",                   "Le Mans (Bugatti)"),
    ("zandvoort",                 "Zandvoort"),
    ("zolder",                    "Zolder"),
    ("mettet",                    "Mettet"),
    ("assen",                     "TT Circuit Assen"),
    ("meppen",                    "Meppen Racepark"),
]

# slug-prefix that defines the event type. Drift / Falken / drift-cup / VR
# events are kept; we tag them in the title for clarity. Trackdays / circuit
# experience / racing experience / testday are normal trackday entries.
SLUG_DATE_RE = re.compile(r"-(\d{1,2})-(\d{1,2})-(\d{4})-(\d+)$")
URL_RE = re.compile(r'/en/event/([a-z0-9-]+)/register')


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        tree = await get_html(LIST_URL.format(page=page))
        html = tree.html or ""
        urls = URL_RE.findall(html)
        if not urls:
            break
        page_added = 0
        for slug in urls:
            ev = _build(slug, html)
            if not ev: continue
            if ev.external_id in seen: continue
            seen.add(ev.external_id)
            out.append(ev)
            page_added += 1
        if page == 1:
            (DEBUG_DIR / "skylimit.html").write_text(html, encoding="utf-8", errors="ignore")
        if page_added == 0 and page > 1:
            break
    return out


def _build(slug: str, page_html: str) -> Optional[RawEvent]:
    m = SLUG_DATE_RE.search(slug)
    if not m:
        return None  # undated slug — skip
    day_s, month_s, year_s, eid = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        event_date = date(int(year_s), int(month_s), int(day_s))
    except ValueError:
        return None
    if event_date < date.today():
        return None

    # Strip the date-id suffix to identify circuit + event type.
    head = slug[:m.start()]
    circuit = None
    for hint, name in CIRCUIT_HINTS:
        if hint in head:
            circuit = name; break
    # Some Skylimit events are at Zolder by default (drift days, racing
    # experience, circuit experience course, testday) — when no circuit
    # hint matches, default to Zolder since that's their home.
    if circuit is None:
        if any(k in head for k in ("circuit-experience", "racing-experience",
                                    "testday", "drift-day", "trackday-zolder",
                                    "advanced-drift")):
            circuit = "Zolder"
        else:
            return None

    # Title: humanise the slug head
    title = head.replace("-", " ").title()
    booking_url = f"{BASE_URL}/en/event/{slug}/register"

    is_drift = "drift" in head
    is_test = "testday" in head

    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=booking_url,
        title=title,
        currency="EUR",
        session=("am_pm" if "afternoon" in head else "day"),
        external_id=eid,
        region="EU",
        notes=("Drift event" if is_drift else ("Test day" if is_test else None)),
    )
