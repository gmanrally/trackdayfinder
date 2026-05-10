"""Lotus on Track — https://www.lotus-on-track.com/

Lotus owners' club running trackdays at UK + EU venues. Single SSR
listing page; each event linked at /lotshop/<circuit>-<weekday>-<dd>-<month>-<year>/.
URL slug carries everything we need; we don't need to fetch detail pages.
"""
from __future__ import annotations
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from ._base import RawEvent, get_html

SOURCE_SLUG = "lotus_on_track"
ORGANISER = "Lotus on Track"
LIST_URL = "https://www.lotus-on-track.com/lotshop/list/"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# Canonical circuit name lookup. Keys are slug-prefixes (everything before
# the trailing weekday-date) lowercased; longest match wins.
SLUG_TO_CIRCUIT = {
    "bilster-berg":            "Bilster Berg",
    "brands-hatch-grand-prix": "Brands Hatch",
    "brands-hatch-indy":       "Brands Hatch",
    "brands-hatch":            "Brands Hatch",
    "cadwell-park":            "Cadwell Park",
    "castle-combe":            "Castle Combe",
    "croft":                   "Croft",
    "dijon-prenois":           "Dijon-Prenois",
    "donington-park-national": "Donington Park",
    "donington-park":          "Donington Park",
    "magny-cours":             "Magny-Cours",
    "mas-du-clos":             "Mas du Clos",
    "mettet":                  "Mettet",
    "nurburgring-grand-prix":  "Nürburgring (Grand Prix)",
    "oulton-park":             "Oulton Park",
    "silverstone-gp":          "Silverstone",
    "silverstone":             "Silverstone",
    "snetterton-300":          "Snetterton",
    "snetterton":              "Snetterton",
    "spa-francorchamps":       "Spa-Francorchamps",
    "zandvoort":               "Zandvoort",
}

WEEKDAYS = {"monday","tuesday","wednesday","thursday","friday","saturday","sunday"}
# Trail tokens stripped before circuit lookup.
SUFFIX_NOISE = {"evening"}

# Slugs that are package/multi-circuit / non-trackday — skip.
SKIP_SLUG_HINTS = ("double-header", "french-frolic", "lm0", "list", "test-track")

DATE_RE = re.compile(r"(\d{1,2})-([a-z]+)-(\d{4})$")


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html(LIST_URL)
    html = tree.html or ""
    (DEBUG_DIR / "lotus_on_track.html").write_text(html, encoding="utf-8", errors="ignore")

    out: list[RawEvent] = []
    seen: set[str] = set()
    for href in re.findall(r'href="(https://www\.lotus-on-track\.com/lotshop/[a-z0-9-]+/?)"', html):
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if slug in seen: continue
        seen.add(slug)
        if any(h in slug for h in SKIP_SLUG_HINTS):
            continue
        ev = _build(slug, href)
        if ev:
            out.append(ev)
    return out


def _build(slug: str, href: str) -> Optional[RawEvent]:
    m = DATE_RE.search(slug)
    if not m: return None
    day_s, month_s, year_s = m.group(1), m.group(2), m.group(3)
    try:
        event_date = datetime.strptime(f"{day_s} {month_s} {year_s}", "%d %B %Y").date()
    except ValueError:
        return None
    if event_date < date.today():
        return None

    # Strip the trailing '-DD-MONTH-YYYY' and any preceding weekday/'evening'.
    head = slug[:m.start()].rstrip("-")
    tokens = head.split("-")
    while tokens and (tokens[-1] in WEEKDAYS or tokens[-1] in SUFFIX_NOISE):
        tokens.pop()
    head_clean = "-".join(tokens)
    if not head_clean: return None

    # Longest-prefix match against the lookup table.
    circuit = None
    for key in sorted(SLUG_TO_CIRCUIT, key=len, reverse=True):
        if head_clean == key or head_clean.startswith(key + "-") or head_clean.startswith(key):
            if head_clean == key or head_clean.startswith(key):
                circuit = SLUG_TO_CIRCUIT[key]
                break
    if not circuit:
        return None

    # Region: everything except Mettet/Bilster/Dijon/Magny/Mas/Nurburgring/Spa/Zandvoort is UK
    eu_circuits = {"Bilster Berg","Dijon-Prenois","Magny-Cours","Mas du Clos","Mettet",
                   "Nürburgring (Grand Prix)","Spa-Francorchamps","Zandvoort"}
    region = "EU" if circuit in eu_circuits else "UK"

    is_evening = "evening" in slug
    return RawEvent(
        source=SOURCE_SLUG,
        organiser=ORGANISER,
        circuit_raw=circuit,
        event_date=event_date,
        booking_url=href,
        title="Evening" if is_evening else None,
        currency="GBP" if region == "UK" else "EUR",
        session=("evening" if is_evening else "day"),
        external_id=slug,
        region=region,
    )
