"""Paddock GT Club (Spain) — static scraper.

Small Spanish open-pitlane organiser running ~10 events/year at Almería-area
circuits. They announce dates via Instagram/Facebook (@paddockgtclub) with no
scrapeable calendar, so we maintain the dates by hand from what they send.

Update EVENTS below when Paddock GT publish a new season / new dates.
Contact: Lucas Gozalvez. Socials: instagram.com/paddockgtclub
"""
from __future__ import annotations
from datetime import date
from ._base import RawEvent

SOURCE_SLUG = "paddock_gt"
ORGANISER = "Paddock GT Club"
BOOKING_URL = "https://www.instagram.com/paddockgtclub/"

# (date, circuit, session, note, price_eur). session: 'am_pm' = split
# 10-14 / 15-18, 'pm' = afternoon-only (sunset events). price None if unknown.
EVENTS: list[tuple[date, str, str, str, Optional[float]]] = [
    (date(2026, 8, 29), "Andalucia Circuit",    "pm",    "Sunset — open pitlane 17:00–21:00",           None),
    (date(2026, 10, 10), "Andalucia Circuit",   "am_pm", "Open pitlane 10:00–14:00 / 15:00–18:00. Max 28 cars; pit garages, timing & photography included.", 300.0),
    (date(2026, 11, 14), "Look and Run Circuit", "am_pm", "Open pitlane 10:00–14:00 / 15:00–18:00",       None),
    (date(2026, 12, 19), "Andalucia Circuit",   "am_pm", "Open pitlane 10:00–14:00 / 15:00–18:00",       None),
]


async def fetch() -> list[RawEvent]:
    today = date.today()
    out: list[RawEvent] = []
    for event_date, circuit, session, note, price_eur in EVENTS:
        if event_date < today:
            continue
        out.append(RawEvent(
            source=SOURCE_SLUG,
            organiser=ORGANISER,
            circuit_raw=circuit,
            event_date=event_date,
            booking_url=BOOKING_URL,
            title="Open Pitlane",
            price_text=f"€{price_eur:.0f}" if price_eur else None,
            currency="EUR",
            session=session,
            notes=note,
            external_id=f"{circuit}|{event_date.isoformat()}",
            region="EU",
        ))
    return out
