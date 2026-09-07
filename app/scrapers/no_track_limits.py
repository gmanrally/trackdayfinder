"""No Track Limits — https://www.eventbrite.co.uk/o/no-track-limits-121164857193

Relaxed track days at Bicester Motion, sold entirely through Eventbrite:
the organiser has no site of its own, so the Eventbrite organiser page is
the source.

That page embeds the data behind its listing as JSON — the date, the
venue with its postcode, the lowest ticket price, whether it has sold out
and whether it has been cancelled — which is what is read, rather than
the rendered cards. The block is found by matching brackets from the
"upcomingEvents" key, so it survives the page being restyled.

Eventbrite's robots allows organiser pages; the disallow list covers
their search, checkout, feeds and internal APIs, none of which is
touched here.

Cancelled dates stay on that page rather than disappearing, so they are
dropped explicitly instead of being published as if they were running.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from ._base import RawEvent, get_html

SOURCE_SLUG = "no_track_limits"
ORGANISER = "No Track Limits"
URL = "https://www.eventbrite.co.uk/o/no-track-limits-121164857193"
EVENTS_KEY = '"upcomingEvents":'
BACKSLASH = chr(92)


def _events(html: str) -> list[dict[str, Any]]:
    """The upcomingEvents array, matched by bracket rather than by regex."""
    at = html.find(EVENTS_KEY)
    if at == -1:
        return []
    start = html.find("[", at)
    if start == -1:
        return []
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == BACKSLASH:
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    found = json.loads(html[start:i + 1])
                except ValueError:
                    return []
                return [e for e in found if isinstance(e, dict)]
    return []


def _day(value: str) -> Optional[date]:
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


async def fetch() -> list[RawEvent]:
    dom = await get_html(URL, timeout=35.0)
    today = date.today()
    out: list[RawEvent] = []
    seen: set[str] = set()
    for raw in _events(dom.html or ""):
        when = _day(raw.get("start_date") or "")
        if not when or when < today:
            continue
        if raw.get("is_cancelled") or raw.get("is_online_event"):
            continue
        name = (raw.get("name") or "").strip()
        venue = raw.get("primary_venue") or {}
        circuit = (venue.get("name") or "").strip()
        if not name or not circuit:
            continue
        ident = str(raw.get("id") or f"{when}-{name}")
        if ident in seen:
            continue
        seen.add(ident)

        tickets = raw.get("ticket_availability") or {}
        lowest = (tickets.get("minimum_ticket_price") or {})
        price = lowest.get("major_value")
        currency = (lowest.get("currency") or "GBP").upper()
        country = ((venue.get("address") or {}).get("country") or "").upper()
        out.append(RawEvent(
            organiser=ORGANISER, source=SOURCE_SLUG, circuit_raw=circuit,
            event_date=when, booking_url=raw.get("url") or URL,
            title=name,
            price_text=(f"£{price}" if price and currency == "GBP"
                        else f"{price} {currency}" if price else None),
            currency=currency,
            sold_out=bool(tickets.get("is_sold_out")),
            region="UK" if country in ("GB", "UK", "") else "EU",
            session="day", external_id=ident,
        ))
    return out
