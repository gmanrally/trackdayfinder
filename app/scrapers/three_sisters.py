"""Three Sisters Circuit (Wigan) — https://threesisterscircuit.co.uk/

Five listing pages — three car (track days / track attacks / drift) and
two bike (bike attack / other). Each event is a `<li>` inside `<ul class="activity-list">`:

  <time datetime="YYYY-MM-DD">…</time>
  <div class="li-text">
    <b>Time:</b> 9am until 5pm<br>
    <b>Price 1:</b> &pound;122 per Novice Car<br>
    …
    <div class="call-us">Places available – call 01942 719030 to book</div>
  </div>

Bookings are by phone only — no per-event URL. We use the listing page
URL as the booking_url so the user lands on the right context."""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html

SOURCE_SLUG = "three_sisters"
ORGANISER = "Three Sisters Circuit"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# (vehicle_type, slug-suffix, title-hint).
PAGES = [
    ("car",  "cars/car-track-days",       "Track Day"),
    ("car",  "cars/car-track-attacks",    "Track Attack"),
    ("car",  "cars/drift",                "Drift Day"),
    ("bike", "bikes/bike-attack",         "Bike Attack"),
    ("bike", "bikes/other-bike-events",   "Bike Event"),
]
BASE_URL = "https://threesisterscircuit.co.uk"

DATE_ATTR_RE = re.compile(r'datetime="(\d{4}-\d{2}-\d{2})"')
PRICE_RE = re.compile(r"(?:&pound;|£)\s*([\d.,]+)", re.I)


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out: list[RawEvent] = []
    seen: set[str] = set()
    for vehicle, path, title in PAGES:
        url = f"{BASE_URL}/{path}"
        try:
            tree = await get_html(url)
        except Exception:
            continue
        html = tree.html or ""
        (DEBUG_DIR / f"three_sisters_{path.replace('/', '_')}.html").write_text(
            html, encoding="utf-8", errors="ignore"
        )
        # Each <li class=" clearfix"> ... </li> inside <ul class="activity-list">.
        # The list is small (current pages have 0–2 events) so a single regex
        # spanning the <li> from <time datetime to the closing </li> is enough.
        list_block_m = re.search(
            r'<ul class="activity-list">(.*?)</ul>', html, re.DOTALL
        )
        if not list_block_m:
            continue
        block = list_block_m.group(1)
        for li_m in re.finditer(r"<li[^>]*>(.*?)</li>", block, re.DOTALL):
            li = li_m.group(1)
            dm = DATE_ATTR_RE.search(li)
            if not dm:
                continue
            try:
                event_date = date.fromisoformat(dm.group(1))
            except ValueError:
                continue
            if event_date < date.today():
                continue
            # Cheapest driver price. Only consider `<b>Price N:</b> £X per …`
            # entries, and exclude passenger / helmet hire / deposit lines.
            prices: list[float] = []
            for pm in re.finditer(
                r"<b>Price\s*\d+:</b>\s*(?:&pound;|£)\s*([\d.,]+)\s*per\s*([^<\n]+)",
                li, re.I,
            ):
                label = pm.group(2).lower()
                if "passenger" in label or "helmet" in label or "deposit" in label:
                    continue
                try:
                    prices.append(float(pm.group(1).replace(",", "")))
                except ValueError:
                    pass
            price_text = f"£{min(prices):.0f}" if prices else None
            # 'Places available' / 'Sold out' indicator within the li.
            li_low = li.lower()
            sold_out = "sold out" in li_low or "sold-out" in li_low or "fully booked" in li_low
            sku = f"{vehicle}|{path}|{event_date.isoformat()}"
            if sku in seen:
                continue
            seen.add(sku)
            out.append(RawEvent(
                source=SOURCE_SLUG,
                organiser=ORGANISER,
                circuit_raw="Three Sisters",
                event_date=event_date,
                booking_url=url,
                title=title,
                price_text=price_text,
                currency="GBP",
                vehicle_type=vehicle,
                sold_out=sold_out,
                session="day",
                external_id=sku,
                region="UK",
            ))
    return out
