"""Template scraper. Copy to <name>.py and implement."""
from __future__ import annotations
from datetime import datetime
from ._base import RawEvent, get_html

SOURCE_SLUG = "example"
ORGANISER = "Example Trackdays"
LISTING_URL = "https://example.com/trackdays"


async def fetch() -> list[RawEvent]:
    tree = await get_html(LISTING_URL)
    out: list[RawEvent] = []
    # TODO: adjust selectors to the real site
    for row in tree.css(".trackday-row"):
        date_text = (row.css_first(".date") or row).text(strip=True)
        circuit = (row.css_first(".circuit") or row).text(strip=True)
        link_node = row.css_first("a")
        url = link_node.attributes.get("href") if link_node else LISTING_URL
        try:
            d = datetime.strptime(date_text, "%d/%m/%Y").date()
        except ValueError:
            continue
        out.append(RawEvent(
            source=SOURCE_SLUG, organiser=ORGANISER,
            circuit_raw=circuit, event_date=d, booking_url=url or LISTING_URL,
        ))
    return out
