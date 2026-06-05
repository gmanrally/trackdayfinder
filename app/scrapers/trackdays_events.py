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

# URLs that point at a bare hostname are too generic to be a useful "Book"
# destination — the user lands on the site root and has no idea which date
# is theirs. Rows like that use the trackdays.events listing as a fallback
# so at least the Book button takes them to a calendar with the row visible.
HOMEPAGE_RE = re.compile(r"^https?://[^/]+/?$", re.I)

# Organisers we already scrape directly. trackdays.events sometimes lists
# speculative or stale dates under these names — but our direct scraper is
# canonical, so we drop the aggregator's row outright whenever its organiser
# name matches one of these (token overlap on ≥1 meaningful word).
KNOWN_DIRECT_ORGANISERS: list[set[str]] = [
    {"curbstone"},
    {"lotus"},                       # "Lotus on Track"
    {"df", "trackdays"}, {"dftrackdays"},
    {"skylimit"},
    {"msv"},                         # "MSV Trackdays" / "MSVT"
    {"javelin"},
    {"opentrack"},
    {"silverstone"},
    {"rma"},
    {"nolimits"}, {"no", "limits"},
    {"goldtrack"}, {"gold", "track"},
    {"goodwood"},
    {"slipandgrip"}, {"slip", "grip"},
    {"trackobsession"}, {"track", "obsession"},
    {"rsr"},                         # "RSR Nürburg" / "RSR Spa"
    {"gedlich"},
    {"pembrey"},
    {"llandow"},
    {"kirkistown"},
    {"three", "sisters"},
    {"castle", "combe"},
    {"motorsport", "events"},        # MSEvents
]


def _matches_known_direct(organiser_tokens: set[str]) -> bool:
    """True if the organiser's tokens contain any known-direct organiser
    fingerprint (all tokens of the fingerprint must be present)."""
    for fp in KNOWN_DIRECT_ORGANISERS:
        if fp.issubset(organiser_tokens):
            return True
    return False


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


def _is_bare_homepage(url: str) -> bool:
    """True if the URL is a bare hostname with no useful path."""
    return bool(url) and bool(HOMEPAGE_RE.match(url))


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

    # The page actually lays out as: all <h2>Month YYYY</h2> first, then all
    # <table class="events"> after. Walking in document order and tracking
    # the last-seen h2 puts every row under the FINAL month (December).
    # Build a {month -> year} lookup up front and trust each row's own date
    # cell for which month to use.
    month_year: dict[int, int] = {}
    for h in tree.css("h2"):
        m = MONTH_HEADER_RE.search(h.text(strip=True))
        if m and m.group(1) in MONTHS:
            month_year[MONTHS[m.group(1)]] = int(m.group(2))

    covered = _build_covered_index()
    out: list[RawEvent] = []
    today = date.today()
    for table in tree.css("table.events"):
        for tr in table.css("tbody tr"):
            ev = _parse_row(tr, month_year, covered)
            if ev and ev.event_date >= today:
                out.append(ev)
    return out


def _parse_row(tr: Node, month_year: dict[int, int], covered: dict) -> Optional[RawEvent]:
    cells = tr.css("td")
    if len(cells) < 5:
        return None

    date_text = cells[0].text(strip=True)
    dm = DATE_RE.search(date_text)
    if not dm:
        return None
    # DATE_RE: (day, month-name). Trust the month name from the cell, look
    # the year up via the page-level {month -> year} map.
    day_num = int(dm.group(1))
    month_name = dm.group(2)
    month = MONTHS.get(month_name)
    if month is None:
        return None
    year = month_year.get(month)
    if year is None:
        return None  # no h2 for this month — page layout drifted; bail
    try:
        event_date = date(year, month, day_num)
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

    # Pick the most useful external link in the row. Anything with a real
    # path is preferred; if the only available link is a bare hostname we
    # fall back to the trackdays.events listing URL so the Book button
    # lands on the aggregator's calendar (where the row is visible) instead
    # of dumping the user on a generic site root.
    booking_url: Optional[str] = None
    homepage_fallback_seen = False
    for a in tr.css("a"):
        href = a.attributes.get("href", "")
        if not href.startswith("http"):
            continue
        if _is_bare_homepage(href):
            homepage_fallback_seen = True
            continue
        booking_url = href
        break
    if booking_url is None:
        if homepage_fallback_seen:
            booking_url = LISTING_URL
        else:
            return None  # no link at all — can't surface this row usefully

    # If the organiser is one we already scrape directly, drop the row.
    # Our direct scraper is canonical; trackdays.events sometimes lists
    # speculative dates under these names that don't match the real site.
    org_tokens = _norm_tokens(organiser_text) - _STOP
    if _matches_known_direct(org_tokens):
        return None

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
