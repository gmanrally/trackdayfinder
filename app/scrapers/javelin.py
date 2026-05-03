"""Javelin Trackdays — https://javelintrackdays.co.uk/trackdays/Upcoming-Events

OpenCart-based site, JS-rendered. Each event is a .product-thumb card:
  .name a            -> title like "6th May - Snetterton" + booking URL
  .description       -> "Wed | 105/92 dba | 300 Circuit"
  .price-normal      -> "£209.00"
  href ends in SKU like SND060526 (DDMMYY)

Pagination: ?page=2 ... ?page=N
"""
from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html_js

SOURCE_SLUG = "javelin"
ORGANISER = "Javelin Trackdays"
BASE_URL = "https://javelintrackdays.co.uk/trackdays/Upcoming-Events"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

SKU_RE = re.compile(r"/([A-Z]{2,4})(\d{6})$")
PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)")
NOISE_RE = re.compile(r"(\d{2,3})\s*/?\s*(\d{2,3})?\s*db", re.I)
TITLE_DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    page_num = 1
    while True:
        url = BASE_URL if page_num == 1 else f"{BASE_URL}?page={page_num}"
        tree = await get_html_js(url, wait_selector=".product-thumb")
        (DEBUG_DIR / f"javelin_p{page_num}.html").write_text(tree.html or "", encoding="utf-8", errors="ignore")

        cards = tree.css(".product-thumb")
        if not cards:
            break
        for card in cards:
            ev = _parse_card(card)
            if ev:
                out.append(ev)

        # decide whether more pages exist
        last_page = 1
        for a in tree.css(".pagination a"):
            href = a.attributes.get("href") or ""
            m = re.search(r"page=(\d+)", href)
            if m:
                last_page = max(last_page, int(m.group(1)))
        if page_num >= last_page:
            break
        page_num += 1
    return out


def _parse_card(card) -> Optional[RawEvent]:
    name_a = card.css_first(".name a")
    if not name_a:
        return None
    title = name_a.text(strip=True)
    href = name_a.attributes.get("href") or BASE_URL

    event_date = _date_from_sku(href) or _date_from_title(title)
    if not event_date:
        return None

    sku = _sku_from_href(href)
    session = _session_from_title(title)

    # circuit name is the part after " - " in title (or before, depending) — Javelin uses "Day Mon - Circuit"
    circuit = title.split(" - ", 1)[1].strip() if " - " in title else title
    # strip session/layout suffixes from circuit name
    circuit = re.sub(r"\s*\((?:Eve|Evening|AM|PM|AM/PM(?: Only)?)\)\s*$", "", circuit, flags=re.I).strip()
    circuit = re.sub(r"\s+AM/PM(?:\s+Only)?\s*$", "", circuit, flags=re.I).strip()

    desc_node = card.css_first(".description")
    desc = desc_node.text(strip=True) if desc_node else ""
    noise_text = None
    nm = NOISE_RE.search(desc)
    if nm:
        noise_text = f"{nm.group(1)}dB" + (f"/{nm.group(2)}dB" if nm.group(2) else "")

    price_node = card.css_first(".price-normal")
    price_text = None
    if price_node:
        # text contains odd encoding for £; strip it down to the number
        raw = price_node.text(strip=True)
        m = PRICE_RE.search(raw.replace(",", ""))
        if m:
            price_text = f"£{m.group(1)}"

    stock_status, spaces_left, sold_out = _parse_stock(card)

    return RawEvent(
        source=SOURCE_SLUG, organiser=ORGANISER,
        circuit_raw=circuit, event_date=event_date, booking_url=href,
        title=title, price_text=price_text, noise_text=noise_text,
        notes=desc or None, sold_out=sold_out,
        spaces_left=spaces_left, stock_status=stock_status,
        session=session, external_id=sku,
    )


def _parse_stock(card) -> tuple[Optional[str], Optional[int], bool]:
    """Read .product-labels span text. Returns (status, spaces_left, sold_out)."""
    label = card.css_first(".product-labels .product-label")
    if not label:
        return None, None, False
    text = label.text(strip=True)
    low = text.lower()
    if "sold out" in low:
        return text, 0, True
    m = re.search(r"(\d+)\s+place", low)
    if m:
        return text, int(m.group(1)), False
    return text, None, False


def _sku_from_href(href: str) -> Optional[str]:
    m = re.search(r"/([^/]+)$", href)
    return m.group(1) if m else None


def _session_from_title(title: str) -> str:
    t = title.lower()
    if re.search(r"\b(eve|evening)\b|\(eve\)", t):
        return "evening"
    if "am/pm" in t:
        return "am_pm"
    if re.search(r"\bam only\b|\(am\)", t):
        return "am"
    if re.search(r"\bpm only\b|\(pm\)", t):
        return "pm"
    return "day"


def _date_from_sku(href: str) -> Optional[date]:
    m = SKU_RE.search(href)
    if not m:
        return None
    dd, mm, yy = int(m.group(2)[0:2]), int(m.group(2)[2:4]), int(m.group(2)[4:6])
    try:
        return date(2000 + yy, mm, dd)
    except ValueError:
        return None


def _date_from_title(title: str) -> Optional[date]:
    m = TITLE_DATE_RE.search(title)
    if not m:
        return None
    day = int(m.group(1))
    mon_str = m.group(2)
    today = date.today()
    for fmt in ("%b", "%B"):
        try:
            mon = datetime.strptime(mon_str[:3] if fmt == "%b" else mon_str, fmt).month
            year = today.year if mon >= today.month else today.year + 1
            return date(year, mon, day)
        except ValueError:
            continue
    return None
