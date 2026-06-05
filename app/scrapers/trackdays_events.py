"""Trackdays.events — https://trackdays.events/en/calendar-4/

Global European calendar aggregator. Used as a gap-filler only — every
row is deduped against our direct scrapers and rows whose organiser link
is a bare homepage or generic listing page are dropped (they leave the
user with a useless 'Book' button).

Page structure:
  <h2>Month YYYY</h2>
  <table class="events"><tbody>
    <tr>
      td 0  date span "Mon 4 May" (no year — taken from preceding h2)
      td 1  country/track "F - Fontenay-le-Comte (circuits de Vendée)"
      td 2  organiser
      td 3  trackday type "open pitlane" / "sessioned"
      td 4  note
      td 5  link to organiser website
"""
from __future__ import annotations
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node, HTMLParser
from sqlmodel import select
from ._base import RawEvent, get_html_js
from ..models import Event, session as db_session

SOURCE_SLUG = "trackdays_events"
ORGANISER = "Trackdays.events"
LISTING_URL = "https://trackdays.events/en/calendar-4/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

DATE_RE = re.compile(r"(?:[A-Za-z]{3,9}\s+)?(\d{1,2})\s+([A-Za-z]+)")
MONTH_HEADER_RE = re.compile(r"([A-Za-z]+)\s+(\d{4})")
COUNTRY_PREFIX_RE = re.compile(r"^([A-Z]{1,3})\s*[-–—]\s*", re.UNICODE)
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}

# URL paths that are unhelpful as a booking destination — they leave the user
# on a generic listing page rather than the actual event. Skip any row whose
# only link looks like one of these.
HOMEPAGE_RE = re.compile(r"^https?://[^/]+/?$", re.I)
INDEX_PATH_RE = re.compile(
    r"^https?://[^/]+/(?:[a-z]{2,3}/)?"
    r"(?:events?|trackdays?|calend(?:rier|ar)|agenda|termine|fechas|rennen|"
    r"shop/?$|home|kontakt|news|page|index)/?(?:\?.*)?$",
    re.I,
)


def _norm_tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", s))


_STOP = {"circuit","de","du","la","le","les","des","et","the","of","and",
         "trackday","trackdays","events","event","day","days"}


def _build_covered_index():
    """Snapshot existing future events from direct scrapers (not from us)
    keyed by date → list of (circuit_tokens, organiser_tokens). Used to
    skip aggregator rows that duplicate a primary-source event."""
    today = date.today()
    covered: dict[date, list[tuple[set[str], set[str]]]] = {}
    with db_session() as s:
        for e in s.exec(select(Event).where(
            Event.event_date >= today,
            Event.source != SOURCE_SLUG,
        )).all():
            covered.setdefault(e.event_date, []).append(
                (_norm_tokens(e.circuit), _norm_tokens(e.organiser))
            )
    return covered


def _is_useless_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return True
    if HOMEPAGE_RE.match(url):
        return True
    if INDEX_PATH_RE.match(url):
        return True
    return False


def _is_duplicate(circuit: str, organiser: str, event_date: date,
                  covered: dict) -> bool:
    """Mirror of the europa scraper's dedup. Same date + ≥1 shared
    meaningful circuit token + ≥1 shared organiser token → already
    covered by a direct scraper."""
    slug_circ = _norm_tokens(circuit) - _STOP
    slug_org = _norm_tokens(organiser) - _STOP
    for db_circ, db_org in covered.get(event_date, []):
        if (slug_circ & (db_circ - _STOP)) and (slug_org & (db_org - _STOP)):
            return True
    return False


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".mydate")
    (DEBUG_DIR / "trackdays_events.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    covered = _build_covered_index()
    out: list[RawEvent] = []
    today = date.today()
    current_month: Optional[int] = None
    current_year: Optional[int] = None
    for node in tree.css("h2, table.events"):
        if node.tag == "h2":
            m = MONTH_HEADER_RE.search(node.text(strip=True))
            if m and m.group(1) in MONTHS:
                current_month = MONTHS[m.group(1)]
                current_year = int(m.group(2))
            continue
        if current_month is None or current_year is None:
            continue
        for tr in node.css("tbody tr"):
            ev = _parse_row(tr, current_year, current_month, covered)
            if ev and ev.event_date >= today:
                out.append(ev)
    return out


def _parse_row(tr: Node, year: int, month: int, covered: dict) -> Optional[RawEvent]:
    cells = tr.css("td")
    if len(cells) < 5:
        return None

    date_text = cells[0].text(strip=True)
    dm = DATE_RE.search(date_text)
    if not dm:
        return None
    try:
        event_date = date(year, month, int(dm.group(1)))
    except ValueError:
        return None

    country_track = cells[1].text(separator=" ", strip=True).strip()
    country_track = re.sub(r"\s+", " ", country_track)
    cm = COUNTRY_PREFIX_RE.match(country_track)
    circuit_raw = country_track[cm.end():].strip() if cm else country_track

    organiser_text = cells[2].text(separator=" ", strip=True) or "Trackdays.events"
    fmt_text = cells[3].text(separator=" ", strip=True)
    note = cells[4].text(separator=" ", strip=True)
    if note in ("-", ""):
        note = None

    # Booking link must look event-specific. We accept any external <a>
    # whose URL has a real path (and isn't a generic listing index).
    booking_url: Optional[str] = None
    for a in tr.css("a"):
        href = a.attributes.get("href", "")
        if not href.startswith("http"):
            continue
        if _is_useless_url(href):
            continue
        booking_url = href
        break
    if booking_url is None:
        return None  # drop rows that would dump the user on a homepage

    # Dedup against direct scrapers — this is a gap-filler only.
    if _is_duplicate(circuit_raw, organiser_text, event_date, covered):
        return None

    title = f"{fmt_text} — {organiser_text}".strip(" —") if fmt_text else organiser_text
    sku = f"{circuit_raw[:30]}|{event_date}|{organiser_text[:30]}"
    return RawEvent(
        source=SOURCE_SLUG, organiser=organiser_text or ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=booking_url,
        title=title, notes=note,
        currency="EUR", region="EU",
        session="day", external_id=sku,
    )
