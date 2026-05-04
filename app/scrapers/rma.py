"""RMA Track Days — https://www.rmatrackdays.com/track-days

Layout: month headers (.date-title-row -> .date-title "May 2026") interleaved with <tr> event rows.
Per-row cells:
  td.event-title a            -> title + /track-days/details/<slug>/<id>
  td[data-title=Date]         -> "Tue 12 May" (year from preceding month header)
  td[data-title="Noise Limit"]-> "Unsilenced" / "98 dB"
  td[data-title="Standard Price"] -> "£599.00"
  td.book-event               -> contains .events-warning ("Almost Sold Out!") /
                                  .events-soldout ("Sold Out") + book button
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "rma"
ORGANISER = "RMA Track Days"
LISTING_URL = "https://www.rmatrackdays.com/track-days"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")
ID_RE = re.compile(r"/(\d+)/?$")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html_js(LISTING_URL, wait_selector=".event-title")
    (DEBUG_DIR / "rma.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    current_month = None
    current_year = None
    # Walk in document order: month headers and event rows
    for node in tree.css(".date-title, tr"):
        # Month header
        if "date-title" in (node.attributes.get("class") or ""):
            month_text = node.text(strip=True)
            m = re.match(r"([A-Za-z]+)\s+(\d{4})", month_text)
            if m:
                try:
                    current_month = datetime.strptime(m.group(1)[:3], "%b").month
                    current_year = int(m.group(2))
                except ValueError:
                    pass
            continue
        # Event row
        if not node.css_first("td.event-title"):
            continue
        if current_month is None or current_year is None:
            continue
        ev = _parse_row(node, current_year, current_month)
        if ev:
            out.append(ev)
    return out


def _parse_row(tr: Node, year: int, month_hint: int) -> Optional[RawEvent]:
    title_td = tr.css_first("td.event-title")
    if not title_td:
        return None
    link = title_td.css_first("a")
    title = link.text(strip=True) if link else title_td.text(strip=True)
    # Skip RMA's multi-day road-trip packages — they're not trackdays.
    low = title.lower()
    if any(k in low for k in (
        "grand tour", "california", "arctic", "road trip", "iceland",
        "alps", "alpine", "norway", "scotland tour",
    )):
        return None
    href = link.attributes.get("href", "") if link else ""
    if href.startswith("/"):
        href = "https://www.rmatrackdays.com" + href
    sku = None
    m = ID_RE.search(href)
    if m:
        sku = m.group(1)

    date_td = tr.css_first('td[data-title="Date"]')
    if not date_td:
        return None
    dt_text = date_td.text(strip=True)
    # parse "Tue 12 May" with year hint
    event_date = _parse_date(dt_text, year, month_hint)
    if not event_date:
        return None

    noise_td = tr.css_first('td[data-title="Noise Limit"]')
    noise_text = noise_td.text(separator=" ", strip=True) if noise_td else None

    price_td = tr.css_first('td[data-title="Standard Price"]') or tr.css_first('td[data-title="Member\'s Price"]')
    price_text = None
    if price_td:
        pm = PRICE_RE.search(price_td.text(strip=True).replace(",", ""))
        if pm:
            price_text = f"£{pm.group(1)}"

    book_td = tr.css_first("td.book-event")
    sold_out = False
    stock_status = None
    spaces_left = None
    if book_td:
        if book_td.css_first(".events-soldout"):
            sold_out = True
            spaces_left = 0
            stock_status = "Sold Out"
        elif book_td.css_first(".events-warning"):
            stock_status = book_td.css_first(".events-warning").text(strip=True) or "Almost Sold Out"

    # circuit name: title prefix before " - " (e.g. "Donington Park Grand Prix - Unsilenced")
    circuit_raw = title.split(" - ", 1)[0] if " - " in title else title

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=href or LISTING_URL,
        title=title, price_text=price_text, noise_text=noise_text,
        sold_out=sold_out, spaces_left=spaces_left, stock_status=stock_status,
        session="day", external_id=sku,
    )


def _parse_date(text: str, year: int, month_hint: int) -> Optional[date]:
    # text like "Tue 12 May" — try with given year, fall back to next year if month rolls over
    tokens = text.replace(",", " ").split()
    for size in (3, 2):
        for i in range(len(tokens) - size + 1):
            window = " ".join(tokens[i:i + size])
            for fmt in ("%a %d %b", "%d %b", "%a %d %B", "%d %B"):
                try:
                    d = datetime.strptime(window, fmt).date()
                    return d.replace(year=year)
                except ValueError:
                    continue
    return None
