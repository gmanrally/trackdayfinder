"""DF Trackdays — https://www.dftrackdays.com/

Dutch operator running mostly at Meppen, Zandvoort, Assen, Zolder, Spa,
Nürburgring Nordschleife, Mettet. SSR ASP.NET site; events linked at
/circuit/trackday/<id>/<circuit>_<DDMMYYYY>/. Each card has a Dutch
day/month label, a price block, and a `trackday_red`/`trackday_green`
indicator (red = sold out)."""
from __future__ import annotations
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html

SOURCE_SLUG = "df_trackdays"
ORGANISER = "DF Trackdays"
LIST_URL = "https://www.dftrackdays.com/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

CIRCUIT_MAP = {
    "meppen":       "Meppen Racepark",
    "zandvoort":    "Zandvoort",
    "assen":        "TT Circuit Assen",
    "zolder":       "Zolder",
    "spa":          "Spa-Francorchamps",
    "nordschleife": "Nürburgring (Nordschleife)",
    "mettet":       "Mettet",
}

URL_RE = re.compile(r"/circuit/trackday/(\d+)/([a-z0-9_]+)/")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html(LIST_URL)
    html = tree.html or ""
    (DEBUG_DIR / "df_trackdays.html").write_text(html, encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    seen: set[str] = set()
    for m in URL_RE.finditer(html):
        eid, slug = m.group(1), m.group(2)
        if eid in seen: continue
        seen.add(eid)
        ev = _build(eid, slug, html, m.start())
        if ev: out.append(ev)
    return out


def _build(eid: str, slug: str, html: str, idx: int) -> Optional[RawEvent]:
    # slug = "<circuit>_DDMMYYYY"
    parts = slug.rsplit("_", 1)
    if len(parts) != 2 or len(parts[1]) != 8:
        return None
    circuit_key, ddmmyyyy = parts
    try:
        event_date = datetime.strptime(ddmmyyyy, "%d%m%Y").date()
    except ValueError:
        return None
    if event_date < date.today():
        return None
    circuit = CIRCUIT_MAP.get(circuit_key)
    if not circuit:
        return None  # unknown circuit — skip rather than guess

    booking_url = "https://www.dftrackdays.com/circuit/trackday/{}/{}/".format(eid, slug)

    # Each card spans roughly idx-200 .. idx+1500 in the HTML.
    # Look for sold-out + price + title within that window.
    win = html[max(0, idx - 200): idx + 2500]
    sold_out = bool(re.search(r"trackday_red", win))
    price_m = re.search(r'LblTrackdayPrice_\d+">€?\s*([\d.,]+)', win)
    price_eur = None
    if price_m:
        try:
            price_eur = float(price_m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            pass
    title_m = re.search(r'LblTrackdayTitle_\d+">([^<]+)<', win)
    title = title_m.group(1).strip() if title_m else None

    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=booking_url,
        title=title,
        price_text=f"€{price_eur:.0f}" if price_eur else None,
        currency="EUR",
        sold_out=sold_out,
        session="day",
        external_id=eid,
        region="EU",
    )
