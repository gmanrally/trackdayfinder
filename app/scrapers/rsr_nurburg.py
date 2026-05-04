"""RSR Nürburgring — https://rsrbooking.com/

The calendar UI uses FullCalendar.js with a JSON feed at:
  https://rsrbooking.com/events/populate?start=YYYY-MM-DD&end=YYYY-MM-DD
returning [{id, title, start, end, ...}, ...].

Listing JSON has no price; per-event detail page has it but fetching ~70 detail
pages per refresh is heavy. We list events without price (price=None) and link
to the detail/booking page so the user clicks through for the cost.
"""
from __future__ import annotations
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
import httpx
from ._base import RawEvent, UA

SOURCE_SLUG = "rsr_nurburg"
ORGANISER = "RSRNurburg"
FEED_URL = "https://rsrbooking.com/events/populate"
# RSR has no public per-event URL. /bookings/select-event is the entry point to
# their booking wizard. The date param isn't read by their UI yet but we send it
# anyway so the URL is self-describing and works if RSR ever adds support.
BOOKING_URL = "https://rsrbooking.com/bookings/select-event?date={date}"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# Tourist Drives (Touristenfahrten) are NOT bookable through RSR — you turn up
# at the Ring and pay per lap. We re-tag those entries to a separate source so
# they're attributed to the Nürburgring directly and link to the official page.
TF_SOURCE = "nurburgring_tf"
TF_ORGANISER = "Nürburgring (Touristenfahrten)"
TF_BOOKING_URL = "https://www.nuerburgring.de/driving/touristdrives"

# Approximate published TF session windows. Real times shift through the season
# (mainly daylight) — this is a useful indicator, not gospel. Source: official
# Nürburgring opening-hours pages (April–September main season).
TF_TIMES = {
    "evening":  "Mon–Fri evenings · ~17:15–19:30",
    "full day": "All-day session · ~08:00–dusk",
    "half day": "Half-day session · morning OR afternoon",
    "1 hour":   "1-hour slot",
}


# Map keywords found in event titles to canonical circuits.
TITLE_CIRCUITS = [
    ("nordschleife", "Nürburgring (Nordschleife)"),
    ("nürburgring", "Nürburgring"),
    ("nurburgring", "Nürburgring"),
    ("gp-strecke", "Nürburgring"),
    ("gp strecke", "Nürburgring"),
    ("monza", "Monza"),
    ("portimao", "Portimão"),
    ("portimão", "Portimão"),
    ("mugello", "Mugello"),
    ("zandvoort", "Zandvoort"),
    ("spa", "Spa-Francorchamps"),
    ("hockenheim", "Hockenheim"),
    ("imola", "Imola"),
    ("paul ricard", "Paul Ricard"),
    ("magny", "Magny-Cours"),
    ("le mans", "Le Mans (Bugatti)"),
    ("estoril", "Estoril"),
    ("jerez", "Jerez"),
    ("barcelona", "Barcelona-Catalunya"),
    ("catalunya", "Barcelona-Catalunya"),
    ("assen", "TT Circuit Assen"),
    ("valencia", "Valencia (Ricardo Tormo)"),
]


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    end = today + timedelta(days=400)
    params = {
        "start": today.isoformat() + "T00:00:00+00:00",
        "end":   end.isoformat()   + "T00:00:00+00:00",
    }
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=30.0) as c:
        r = await c.get(FEED_URL, params=params)
        r.raise_for_status()
        events = r.json()
    (DEBUG_DIR / "rsr_nurburg.json").write_text(r.text, encoding="utf-8")

    out: list[RawEvent] = []
    seen_keys = set()
    for ev in events:
        title = (ev.get("title") or "").strip()
        try:
            event_date = datetime.strptime(ev["start"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if not title or event_date < today:
            continue

        eid = str(ev.get("id") or "")
        # The feed returns the same event multiple times across days for multi-day
        # spans — dedup on (id, start_date).
        key = f"{eid}|{event_date}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        circuit = _circuit_from_title(title)
        is_package = bool(re.search(r"\(\s*\d+\s*days?\s*\)|premium|package|trip", title, re.I))

        # Touristenfahrten — re-tag to Nürburgring direct, link to official page
        # and add typical session-time hint based on the title's session marker.
        low_title = title.lower()
        if "tourist drives" in low_title or "touristenfahrten" in low_title:
            time_hint = None
            for marker, hint in TF_TIMES.items():
                if marker in low_title:
                    time_hint = hint
                    break
            display_title = f"{title} — {time_hint}" if time_hint else title
            out.append(RawEvent(
                source=TF_SOURCE, organiser=TF_ORGANISER,
                circuit_raw="Nürburgring (Nordschleife)",
                event_date=event_date,
                booking_url=TF_BOOKING_URL,
                title=display_title,
                notes=time_hint,
                currency="EUR", region="EU",
                session="day", external_id=eid,
            ))
            continue

        booking_url = BOOKING_URL.format(date=event_date.strftime("%d-%m-%Y"))
        out.append(RawEvent(
            source=SOURCE_SLUG, organiser=ORGANISER,
            circuit_raw=circuit, event_date=event_date, booking_url=booking_url,
            title=title, currency="EUR", region="EU",
            is_package=is_package, session="day", external_id=eid,
        ))
    return out


def _circuit_from_title(title: str) -> str:
    low = title.lower()
    for token, name in TITLE_CIRCUITS:
        if token in low:
            return name
    return "Nürburgring"  # default — RSR is Ring-centric
