"""Goodwood Motor Circuit — https://www.goodwood.com/motorsport/motor-circuit/diary/

The diary lists ALL motor-circuit events (Breakfast Club, festivals, race meets,
track days, etc.). We filter to event titles containing "Track Day" excluding
"Private Track Day" (corporate-only bookings).

DOM structure (top-down):
  div.events-month                            month group
    .events-month__sticky-text  -> "Nov2026" (was "May" / "2026")
    li.events-day                              one date
      .events-month__sticky-text -> "Sun 03"
      ul.event-day-list
        li.event-day                            one event
          h3.heading-32           -> title
          p.alt-18                -> description
          .meta-chip span.body-14 -> time / chips
          a (Read More)           -> event detail URL
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "goodwood"
ORGANISER = "Goodwood Motor Circuit"
LISTING_URL = "https://www.goodwood.com/motorsport/motor-circuit/diary/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DAY_RE = re.compile(r"(\d{1,2})")
NOISE_RE = re.compile(r"(\d{2,3})\s*db", re.I)
MONTH_NAMES = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}
# The diary used to head each group with a full month name and now writes it
# short — "Nov2026" where it said "May". Matching on the first three letters
# takes both, and is why this is keyed that way rather than on the full name.
MONTH_BY_PREFIX = {name[:3].lower(): num for name, num in MONTH_NAMES.items()}
MONTH_YEAR_RE = re.compile(r"([A-Za-z]{3,9})\s*(20\d{2})")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".event-day")
    (DEBUG_DIR / "goodwood.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    for month_div in tree.css(".events-month"):
        month, year = _parse_month(month_div)
        if not month:
            continue
        for day_li in month_div.css(".events-day"):
            day = _parse_day_number(day_li)
            if not day:
                continue
            try:
                event_date = date(year, month, day)
            except ValueError:
                continue
            for ev_li in day_li.css(".event-day"):
                ev = _parse_event(ev_li, event_date)
                if ev:
                    out.append(ev)
    return out


def _parse_month(month_div: Node) -> tuple[Optional[int], Optional[int]]:
    """Month and year off the group's own header.

    Read from the first .events-month__sticky-text rather than from every
    span under it: the same class labels each date inside the group, so the
    old combined text was "Nov2026 Nov Nov 2026 Sun 01 Sat 07 …" and a
    weekday could be mistaken for a month once abbreviations were allowed.
    """
    label = month_div.css_first(".events-month__sticky-text")
    if not label:
        return None, None
    m = MONTH_YEAR_RE.search(label.text(separator=" ", strip=True))
    if not m:
        return None, None
    month = MONTH_BY_PREFIX.get(m.group(1)[:3].lower())
    if not month:
        return None, None
    return month, int(m.group(2))


def _parse_day_number(day_li: Node) -> Optional[int]:
    label = day_li.css_first(".events-month__sticky-text")
    if not label:
        return None
    m = DAY_RE.search(label.text(strip=True))
    return int(m.group(1)) if m else None


def _parse_event(ev: Node, event_date: date) -> Optional[RawEvent]:
    title_node = ev.css_first("h3")
    if not title_node:
        return None
    title = title_node.text(strip=True)
    low = title.lower()
    if "track day" not in low:
        return None
    if "private track day" in low:
        return None  # corporate exclusive bookings, not bookable by public

    desc_node = ev.css_first("p")
    desc = desc_node.text(separator=" ", strip=True) if desc_node else None

    chips = [s.text(strip=True) for s in ev.css(".meta-chip span") if s.text(strip=True)]
    time_text = next((c for c in chips if re.search(r"\d{1,2}:\d{2}", c)), None)

    noise_text = None
    nm = NOISE_RE.search(title) or (NOISE_RE.search(desc) if desc else None)
    if nm:
        noise_text = f"{nm.group(1)}dB"

    link_node = ev.css_first("a[href*='goodwood.com']") or ev.css_first("a")
    href = link_node.attributes.get("href", LISTING_URL) if link_node else LISTING_URL
    if href.startswith("/"):
        href = "https://www.goodwood.com" + href
    sku = href.rstrip("/").rsplit("/", 1)[-1]

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw="Goodwood", event_date=event_date, booking_url=href,
        title=title, noise_text=noise_text, notes=desc,
        session="day", external_id=f"{sku}|{event_date}|{time_text or ''}",
    )
