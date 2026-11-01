"""Drive Académie — https://www.driveacademie.com

Open-pitlane car trackdays at the Circuit de Mirecourt (Juvaincourt, Vosges),
a 3.75km track that opened in 2023. Both aggregators we read have carried
Drive Académie's Mirecourt dates, but pointing at their own listing pages;
this reads the organiser's shop directly, so the Book button lands where the
entry is actually sold. They asked to be listed, and sent the 2027 calendar
by email — the dates here were reconciled against it and agree exactly.

The site is WooCommerce, so the Store API answers the whole calendar in one
request: the date, the live price, stock, and a product description carrying
the published noise limit, car cap and vehicle restrictions. No browser, so
nothing here can leak one.

Four things worth knowing before editing this:

- The date is read from the product slug, not the display name. Slugs are
  unaccented and consistently "…-<day>-<month>-<year>" ("…-1-aout-2027"),
  where the name is free prose with accents, ordinals and inconsistent case
  ("Dimanche 1er août 2027", "SAMEDI 14 NOVEMBRE 2026"). The name is only a
  fallback.

- Weekend and public-holiday days are variable products offering a full day
  or one of two part-day entries; weekday days are simple products sold as a
  full day only. Either way this emits one row per date, priced as the full
  day, because a full day is what the site's price column compares. On a
  variable product the full day is necessarily the dearest option, so the
  price range's upper bound is it — if a dearer non-full-day option is ever
  added (a coaching package, say), that assumption is the thing to revisit.

- "Trackday Privatisé" products are corporate hire, not public entries. They
  are excluded by name; they are also unpurchasable and priced at zero, which
  is the backstop.

- ingest._infer_session re-reads title and notes and will move a "day" event
  to am/pm/am_pm when it finds words like "morning", "afternoon", "half day"
  or "evening" in them. The note text below avoids those words deliberately
  — describing the part-day entries in the obvious English would silently
  relabel every weekend day as a part-day event.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ._base import RawEvent, get_json

SOURCE_SLUG = "drive_academie"
ORGANISER = "Drive Académie"
BASE = "https://www.driveacademie.com"
STORE = BASE + "/wp-json/wc/store/v1"
CATEGORIES_URL = STORE + "/products/categories?per_page=100"
PRODUCTS_URL = STORE + "/products?category={cat}&per_page=100&page={page}"
# Their shop also sells driving experiences, hire and gift vouchers. Only this
# category is "a day you turn up to in your own car".
CATEGORY_SLUG = "trackday-auto"
MAX_PAGES = 10

# Slug months are unaccented; the accented spellings are for the name fallback.
MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "décembre": 12,
}
# Trailing "<day>[er]-<month>-<year>", separated by hyphens in a slug and by
# spaces in a display name.
DATE_RE = re.compile(r"(\d{1,2})(?:er)?[-\s]([a-zà-ÿ]+)[-\s](\d{4})\s*$")
TAGS_RE = re.compile(r"<[^>]+>")
# "Niveau sonore maximum : 100 dB en dynamique" — taken from this line rather
# than the whole description, which also quotes engine and insurance figures.
NOISE_RE = re.compile(r"niveau sonore[^.\n]*", re.I)
# "Seulement 25 voitures maximum !" — published on the weekday days only; the
# weekend ones say "la capacité du circuit" and name no number, so no number
# is shown for them.
CARS_RE = re.compile(r"(\d{1,3})\s*voitures?\s*maximum", re.I)
# "Véhicules interdits : monoplaces à roues découvertes, karts, superkarts et
# véhicules électriques."
NO_EV_RE = re.compile(r"v[eé]hicules?\s+[eé]lectriques?\s+interdits?", re.I)
# "Session féminine offerte de 13h30 à 14h00 pour les accompagnantes inscrites"
WOMENS_RE = re.compile(r"session\s+f[eé]minine", re.I)


def _text(html: str | None) -> str:
    """Description markup as plain text, for the regexes above."""
    return TAGS_RE.sub(" ", html or "").replace("&nbsp;", " ")


def _day(slug: str, name: str) -> Optional[date]:
    for candidate in (slug or "", (name or "").lower()):
        m = DATE_RE.search(candidate)
        if not m:
            continue
        month = MONTHS.get(m.group(2))
        if not month:
            continue
        try:
            return date(int(m.group(3)), month, int(m.group(1)))
        except ValueError:
            continue
    return None


def _amount(raw: str | None, minor_unit: int) -> Optional[float]:
    """A Store API money string ("30000" at minor unit 2) as 300.0."""
    if raw in (None, ""):
        return None
    try:
        return int(raw) / (10 ** max(minor_unit, 0))
    except (TypeError, ValueError):
        return None


def _full_day_price(product: dict) -> Optional[float]:
    """What a full day costs today, in euros.

    `prices.price` is the live price of the cheapest purchasable option, which
    on a weekend day is a part-day entry. Where the product offers a full day,
    the range's upper bound is that full day (see the module note).
    """
    prices = product.get("prices") or {}
    minor = prices.get("currency_minor_unit")
    minor = minor if isinstance(minor, int) else 2
    rng = prices.get("price_range") or {}
    has_full_day = any(
        "journ" in str(attr.get("value", "")).lower()
        for variation in (product.get("variations") or [])
        for attr in (variation.get("attributes") or [])
    )
    if has_full_day and rng.get("max_amount"):
        return _amount(rng["max_amount"], minor)
    return _amount(prices.get("price"), minor)


def _notes(body: str) -> str:
    """The conditions worth carrying, read off the organiser's own copy.

    Phrased to avoid the words ingest._infer_session looks for, so a full-day
    event stays a full-day event.
    """
    parts = ["Open pit lane."]
    cars = CARS_RE.search(body)
    if cars:
        parts.append(f"{cars.group(1)} cars maximum.")
    if NO_EV_RE.search(body) or "roues d" in body.lower():
        parts.append("Series, sportscars, prepared and closed-wheel competition "
                     "cars, including closed-wheel prototypes. No single-seaters, "
                     "karts or electric vehicles.")
    if "responsabilit" in body.lower():
        parts.append("Driver third-party liability insurance and one passenger "
                     "included.")
    if WOMENS_RE.search(body):
        parts.append("Includes a free 13:30–14:00 women-only track session "
                     "for registered accompanying guests.")
    return " ".join(parts)


async def _category_id() -> int:
    cats, _ = await get_json(CATEGORIES_URL)
    for cat in cats if isinstance(cats, list) else []:
        if (cat.get("slug") or "").lower() == CATEGORY_SLUG:
            return int(cat["id"])
    # Deliberately loud: a renamed category would otherwise look like an
    # organiser who had quietly stopped running trackdays.
    raise RuntimeError(f"no '{CATEGORY_SLUG}' category at {BASE}")


async def _products(cat: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        batch, _ = await get_json(PRODUCTS_URL.format(cat=cat, page=page))
        if not isinstance(batch, list) or not batch:
            break
        out += batch
        if len(batch) < 100:
            break
    return out


def _parse(product: dict, today: date) -> Optional[RawEvent]:
    slug = (product.get("slug") or "").lower()
    name = (product.get("name") or "").strip()
    # Corporate hire, sold privately rather than by the place.
    if "privatis" in slug or "privatis" in name.lower():
        return None
    when = _day(slug, name)
    if not when or when < today:
        return None

    price = _full_day_price(product)
    purchasable = bool(product.get("is_purchasable"))
    if not price and not purchasable:
        return None        # voucher or placeholder, nothing to sell

    body = _text(product.get("description"))
    noise = NOISE_RE.search(body)
    spaces = product.get("low_stock_remaining")
    spaces = spaces if isinstance(spaces, int) else None
    # "Trackday Semaine" is their name for the weekday days: one price, a full
    # day, and a smaller car count than the weekend ones. Read from both slug
    # and name — the first of the 2027 weekday days is named "Trackday
    # Semaine" but was given a slug without it, and labelling that Monday a
    # weekend day also promised it the weekend capacity.
    weekday_format = "semaine" in slug or "semaine" in name.lower()

    return RawEvent(
        organiser=ORGANISER, source=SOURCE_SLUG,
        circuit_raw="Circuit de Mirecourt", event_date=when,
        booking_url=(product.get("permalink") or BASE),
        title="Open pitlane (weekday)" if weekday_format else "Open pitlane (weekend)",
        price_text=f"€{price:.2f}" if price is not None else None,
        currency=(product.get("prices") or {}).get("currency_code") or "EUR",
        noise_text=noise.group(0) if noise else None,
        vehicle_type="car", session="day", region="EU",
        sold_out=not bool(product.get("is_in_stock", True)),
        spaces_left=spaces,
        stock_status=f"{spaces} left" if spaces is not None else None,
        notes=_notes(body),
        external_id=str(product.get("id") or slug),
    )


async def fetch() -> list[RawEvent]:
    products = await _products(await _category_id())
    today = date.today()
    out: list[RawEvent] = []
    seen: set[str] = set()
    for product in products:
        event = _parse(product, today)
        if event and event.external_id not in seen:
            seen.add(event.external_id or "")
            out.append(event)
    return out
