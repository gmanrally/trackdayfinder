"""Silverstone Circuit — official trackdays
  https://www.silverstone.co.uk/track-and-testing/car-track-days
  https://www.silverstone.co.uk/track-and-testing/bike-track-days

Drupal Views table. Per-row cells (td.views-field-field-...):
  field-track-day-date    -> <time datetime="2026-04-30T12:00:00Z"> + "More info" link
  field-track-day-circuit -> circuit layout (e.g. "Grand Prix", "National") — text contains SVG style noise
  field-format-masterclass -> "Open Pit Lane" / "Sessioned"
  field-drive-by          -> "102 dB(A)"
  field-track-day-current-price -> "From £608"
  views-field-nothing     -> "Book now" button (visit.silverstone.co.uk URL)
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from selectolax.parser import Node
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "silverstone"
ORGANISER = "Silverstone"
URLS = {
    "car":  "https://www.silverstone.co.uk/track-and-testing/car-track-days",
    "bike": "https://www.silverstone.co.uk/track-and-testing/bike-track-days",
}
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    for vehicle, url in URLS.items():
        tree = await get_html_js(url, wait_selector="td.views-field-field-track-day-date")
        (DEBUG_DIR / f"silverstone_{vehicle}.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")
        for cell in tree.css("td.views-field-field-track-day-date"):
            ev = _parse_row(cell.parent, vehicle)
            if ev:
                out.append(ev)
    return out


def _parse_row(tr: Node, vehicle: str) -> Optional[RawEvent]:
    date_td = tr.css_first("td.views-field-field-track-day-date")
    if not date_td:
        return None
    time_node = date_td.css_first("time")
    if not time_node:
        return None
    iso = time_node.attributes.get("datetime") or ""
    try:
        event_date = datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
    except ValueError:
        return None

    detail_link = date_td.css_first("a")
    detail_url = (detail_link.attributes.get("href") if detail_link else "") or ""
    sku = detail_url.rstrip("/").rsplit("/", 1)[-1] if detail_url else None

    layout_td = tr.css_first("td.views-field-field-track-day-circuit")
    layout = ""
    if layout_td:
        # The cell contains an inline SVG with embedded CSS noise (".st0{fill:#1D1934;}").
        # The actual layout name is in a sibling text node after the SVG. Grab non-SVG text.
        for child in layout_td.css("span"):
            if child.css_first("svg"):
                continue
            t = child.text(separator=" ", strip=True)
            t = re.sub(r"\.[\w-]+\s*\{[^}]*\}", "",t).strip()
            if t:
                layout = t
                break
        if not layout:
            raw = layout_td.text(separator=" ", strip=True)
            raw = re.sub(r"\.[\w-]+\s*\{[^}]*\}", "",raw).strip()
            layout = raw
    # Silverstone is a single circuit; layout distinguishes (GP / National / International / Stowe)
    circuit_raw = f"Silverstone {layout}".strip()

    fmt_td = tr.css_first("td.views-field-field-format-masterclass")
    fmt = fmt_td.text(separator=" ", strip=True) if fmt_td else ""

    noise_td = tr.css_first("td.views-field-field-drive-by")
    noise_text = noise_td.text(separator=" ", strip=True) if noise_td else None

    price_td = tr.css_first("td.views-field-field-track-day-current-price")
    price_text = None
    if price_td:
        m = PRICE_RE.search(price_td.text(strip=True).replace(",", ""))
        if m:
            price_text = f"£{m.group(1)}"

    book_td = tr.css_first("td.views-field-nothing")
    booking_url = detail_url or URLS[vehicle]
    if book_td:
        a = book_td.css_first("a")
        if a and a.attributes.get("href"):
            booking_url = a.attributes["href"]

    row_text = tr.text(separator=" ", strip=True).lower()
    sold_out = "sold out" in row_text or "soldout" in row_text
    stock_status = "Sold Out" if sold_out else None
    spaces_left = 0 if sold_out else None

    title = f"{fmt} — Silverstone {layout}".strip(" —") if fmt else f"Silverstone {layout}"

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit_raw, event_date=event_date, booking_url=booking_url,
        title=title, price_text=price_text, noise_text=noise_text,
        vehicle_type=vehicle, sold_out=sold_out, spaces_left=spaces_left,
        stock_status=stock_status, session="day", external_id=sku,
    )
