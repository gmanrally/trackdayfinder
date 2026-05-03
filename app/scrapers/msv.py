"""MSV Trackdays — separate car / bike calendars.
  https://car.msvtrackdays.com/Calendar
  https://bike.msvtrackdays.com/Calendar

Each row is a `.grid-x` containing:
  .event-date           "Wed 06 May"
  .event-name           "General Track Day"
  .event-venue          "Donington Park"
  .event-circuit-layout "National"
  .availability-{excellent,low,...}  + text "Available" / "Limited"
  a.more-info[href]     "/calendar/car/doningtonpark/2026/5/6"  -> date in URL!
  a.more-info span      "From £325"
"""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "msv"
ORGANISER = "MSV Trackdays"
URLS = {
    "car":  "https://car.msvtrackdays.com/Calendar",
    "bike": "https://bike.msvtrackdays.com/Calendar",
}
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

URL_DATE_RE = re.compile(r"/calendar/(?:car|bike)/([^/]+)/(\d{4})/(\d{1,2})/(\d{1,2})", re.I)
PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    for vehicle, url in URLS.items():
        tree = await get_html_js(url, wait_selector=".event-name")
        (DEBUG_DIR / f"msv_{vehicle}.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")
        for name_node in tree.css(".event-name"):
            row = _row_container(name_node)
            if not row:
                continue
            ev = _parse_row(row, vehicle, url)
            if ev:
                out.append(ev)
    return out


def _row_container(node: Node) -> Optional[Node]:
    """Walk up until a container with both event-date and event-venue is found."""
    cur = node
    for _ in range(8):
        cur = cur.parent
        if not cur:
            return None
        h = cur.html or ""
        if "event-date" in h and "event-venue" in h and "more-info" in h and len(h) < 6000:
            return cur
    return None


def _parse_row(row: Node, vehicle: str, base_url: str) -> Optional[RawEvent]:
    link = row.css_first("a.more-info")
    if not link:
        return None
    href = link.attributes.get("href") or ""
    m = URL_DATE_RE.search(href)
    if not m:
        return None
    circuit_slug, year, mm, dd = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    try:
        event_date = date(year, mm, dd)
    except ValueError:
        return None

    domain = "https://car.msvtrackdays.com" if vehicle == "car" else "https://bike.msvtrackdays.com"
    full_url = href if href.startswith("http") else domain + href
    sku = href.lstrip("/").replace("/", "-")

    title = (row.css_first(".event-name").text(strip=True) if row.css_first(".event-name") else "") or None
    venue = (row.css_first(".event-venue").text(strip=True) if row.css_first(".event-venue") else "") or ""
    layout = (row.css_first(".event-circuit-layout").text(strip=True) if row.css_first(".event-circuit-layout") else "")
    circuit_raw = f"{venue} {layout}".strip() if layout else venue

    price_text = None
    btn_text = link.text(strip=True)
    pm = PRICE_RE.search(btn_text.replace(",", ""))
    if pm:
        price_text = f"£{pm.group(1)}"

    # Availability: MSV uses several variants in the same cell.
    #   span.availability-excellent "Available"
    #   span.availability-low       "Limited"
    #   span.text-warning           "Sold Out"  (sometimes with "Reserve list" nearby)
    #   span.text-danger            "Sold Out"
    stock_status = None
    sold_out = False
    spaces_left = None
    avail_cell = row.css_first("div.cell.small-3.medium-2.text-center")
    avail_text = avail_cell.text(separator=" ", strip=True) if avail_cell else ""
    avail_low = avail_text.lower()
    if "sold out" in avail_low or "fully booked" in avail_low or "full" == avail_low:
        sold_out = True
        spaces_left = 0
        stock_status = "Reserve list" if "reserve" in avail_low or "waiting" in avail_low else "Sold Out"
    elif "limited" in avail_low or "low" in avail_low:
        stock_status = "Limited"
    elif "available" in avail_low:
        stock_status = None  # default — don't badge

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=full_url,
        title=title, price_text=price_text, vehicle_type=vehicle,
        sold_out=sold_out, spaces_left=spaces_left, stock_status=stock_status,
        session="day", external_id=sku,
    )
