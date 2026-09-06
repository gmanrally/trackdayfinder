"""Open Pitlane Events — https://www.open-pitlane-events.com/event-list

A Dutch-run organiser putting on open-pitlane days at Circuit Clastres in
northern France, which nothing else we scrape covers.

Their site is Wix, and the rendered list is no use: dates arrive as Dutch
abbreviations ("do 08 okt") with no year on them. Wix also embeds the
data behind that list in the page as JSON — real ISO dates, the venue
with its coordinates and country, the ticket price and the event slug —
so that is what is read. It is found by walking the blob rather than by
its widget key, which is generated per site and would change if the page
were rebuilt.

The date is taken from the ISO start, whose UTC day matches the local day
for anything starting after about 01:00 local — true of every trackday,
which start in the morning.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterator, Optional

from ._base import RawEvent, get_html

SOURCE_SLUG = "open_pitlane"
ORGANISER = "Open Pitlane Events"
LIST_URL = "https://www.open-pitlane-events.com/event-list"
EVENT_URL = "https://www.open-pitlane-events.com/event-details/{slug}"
WARMUP_KEY = '"appsWarmupData":'


def _warmup(html: str) -> Optional[dict]:
    """The appsWarmupData object, matched by brace rather than by regex."""
    at = html.find(WARMUP_KEY)
    if at == -1:
        return None
    start = html.find("{", at + len(WARMUP_KEY))
    if start == -1:
        return None
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except ValueError:
                    return None
    return None


def _events_in(node: Any) -> Iterator[dict]:
    """Every event object in the blob, wherever the widget put them."""
    if isinstance(node, dict):
        found = node.get("events")
        if isinstance(found, list):
            for item in found:
                if isinstance(item, dict) and "scheduling" in item:
                    yield item
        for value in node.values():
            yield from _events_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from _events_in(value)


def _day(iso: str) -> Optional[date]:
    try:
        return datetime.strptime((iso or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


async def fetch() -> list[RawEvent]:
    dom = await get_html(LIST_URL, timeout=35.0)
    blob = _warmup(dom.html or "")
    if not blob:
        return []

    today = date.today()
    out: list[RawEvent] = []
    seen: set[str] = set()
    for raw in _events_in(blob):
        config = ((raw.get("scheduling") or {}).get("config") or {})
        when = _day(config.get("startDate") or "")
        if not when or when < today:
            continue
        title = (raw.get("title") or "").strip()
        location = raw.get("location") or {}
        circuit = (location.get("name") or "").strip()
        if not title or not circuit:
            continue
        slug = (raw.get("slug") or "").strip()
        ident = str(raw.get("id") or slug or f"{when}-{title}")
        if ident in seen:
            continue
        seen.add(ident)

        ticketing = (raw.get("registration") or {}).get("ticketing") or {}
        price = (ticketing.get("lowestPrice") or "").strip() or None
        currency = (ticketing.get("currency") or "EUR").strip().upper()
        country = ((location.get("fullAddress") or {}).get("country") or "").upper()
        out.append(RawEvent(
            organiser=ORGANISER, source=SOURCE_SLUG, circuit_raw=circuit,
            event_date=when,
            booking_url=EVENT_URL.format(slug=slug) if slug else LIST_URL,
            title=title, price_text=price, currency=currency,
            region="UK" if country in ("GB", "UK") else "EU",
            session="day", external_id=ident,
            # Wix states this outright; the registration status beside it
            # is an enum whose meaning is not documented here, and reading
            # it as sold-out marked both open events sold out.
            sold_out=bool(ticketing.get("soldOut")),
            notes=(location.get("address") or "").strip() or None,
        ))
    return out
