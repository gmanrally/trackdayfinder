"""Cross-promotion for our sibling site.

TrackdayFinder and MotorsportEventFinder serve two halves of the same
audience — people who drive their car on a circuit, and people who compete
— so each site advertises the other above the footer and when a search
comes up empty.

The event count is read from the sibling's /api/meta, cached in-process and
refreshed on a timer. Nothing here can block or break a page render: if the
sibling is unreachable the promo simply renders without a number.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx

SIBLING = {
    "name": "MotorsportEventFinder.co.uk",
    "url": "https://motorsporteventfinder.co.uk/",
    "icon": "/static/sibling-icon.svg",
    "headline": "Ready to stop lapping and start racing?",
    # Rendered as: "…lists <count> UK motorsport events" — or the plain
    # wording when we have no count to show.
    "noun": "UK motorsport events",
    "detail": "Stage rallies, circuit racing, hillclimbs, ovals and speedway, "
              "with entry fees and closing dates.",
    "cta": "Browse motorsport events",
    "meta_url": "https://motorsporteventfinder.co.uk/api/meta",
}

TIMEOUT = 6.0
_count: Optional[int] = None
_fetched_at: Optional[datetime] = None


async def refresh() -> Optional[int]:
    """Pull the sibling's upcoming-event count. Swallows every failure —
    a promo without a number is fine, a 500 on our own pages is not."""
    global _count, _fetched_at
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(SIBLING["meta_url"],
                            headers={"User-Agent": "TrackdayFinder/1.0 (sibling promo)"})
            r.raise_for_status()
            n = int(r.json().get("events_upcoming") or 0)
        if n > 0:
            _count, _fetched_at = n, datetime.utcnow()
    except Exception:
        pass                      # keep whatever we had; try again next tick
    return _count


def promo() -> dict:
    """Template view of the sibling: config plus the cached count."""
    return {**SIBLING, "count": _count}
