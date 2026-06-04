"""Run scrapers and upsert results into the DB."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, date as _date
from sqlmodel import select, delete as sql_delete
from .models import Event, ScrapeRun, EventSnapshot, init_db, session
from .normalise import canonical_circuit, parse_price, parse_noise, make_dedup_key, to_gbp
from .scrapers import SCRAPERS
from .circuit_noise import CIRCUIT_STATIC_NOISE_DB

# Stale-event guardrails. After a successful per-source scrape we delete
# upcoming events from that source whose last_seen is older than this many
# days. Skipped entirely when the scrape returned fewer than MIN_EVENTS_TO_PRUNE
# events — a transient outage shouldn't wipe everything.
STALE_PRUNE_DAYS = 14
MIN_EVENTS_TO_PRUNE = 3


def _prune_stale(source: str) -> int:
    """Delete upcoming events from `source` whose last_seen is older than
    STALE_PRUNE_DAYS. Returns number deleted. Safe to call repeatedly."""
    cutoff = datetime.utcnow() - timedelta(days=STALE_PRUNE_DAYS)
    today = _date.today()
    with session() as s:
        stmt = sql_delete(Event).where(
            Event.source == source,
            Event.event_date >= today,
            Event.last_seen.is_not(None),
            Event.last_seen < cutoff,
        )
        result = s.exec(stmt)
        n = result.rowcount or 0
        s.commit()
    return n


def _infer_session(session: str | None, title: str | None, notes: str | None) -> str | None:
    """If the scraper said 'day' (or nothing) but the title/notes suggest
    a partial-day session, refine it. Trust an explicit non-'day' value."""
    if session and session not in ("day", "", None):
        return session
    blob = " ".join(filter(None, [title, notes])).lower()
    if not blob:
        return session
    if "evening" in blob or "twilight" in blob:
        return "evening"
    if "am only" in blob or "morning" in blob or "am session" in blob:
        return "am"
    if "pm only" in blob or "afternoon" in blob or "pm session" in blob:
        return "pm"
    if "half day" in blob or "half-day" in blob or "am+pm" in blob or "am/pm" in blob:
        return "am_pm"
    return session or "day"


async def run_one(slug: str) -> tuple[int, str | None]:
    init_db()
    module = SCRAPERS[slug]
    run = ScrapeRun(source=slug)
    n = 0
    err: str | None = None
    try:
        raws = await module.fetch()
        with session() as s:
            for raw in raws:
                circuit = canonical_circuit(raw.circuit_raw)
                # Honour raw.source if a scraper splits its output into multiple
                # logical sources (e.g. RSR pulls out Touristenfahrten as "nurburgring_tf").
                event_source = raw.source or slug
                key = make_dedup_key(event_source, circuit, raw.event_date, raw.organiser,
                                     external_id=raw.external_id, session=raw.session)
                existing = s.exec(select(Event).where(Event.dedup_key == key)).first()
                # Snapshot the previous state BEFORE we overwrite it, so we can
                # detect price/availability changes and store history.
                prev = None
                if existing:
                    prev = (existing.price_gbp, existing.spaces_left, existing.sold_out)
                ev = existing or Event(dedup_key=key, source=event_source, organiser=raw.organiser,
                                       circuit=circuit, circuit_raw=raw.circuit_raw,
                                       event_date=raw.event_date, booking_url=raw.booking_url)
                ev.source = event_source
                ev.circuit = circuit
                ev.circuit_raw = raw.circuit_raw
                ev.event_date = raw.event_date
                ev.booking_url = raw.booking_url
                ev.title = raw.title
                ev.vehicle_type = raw.vehicle_type or "car"
                ev.group_level = raw.group_level
                native_price = parse_price(raw.price_text or "")
                ev.price_native = native_price
                ev.currency = (raw.currency or "GBP").upper()
                ev.price_gbp = to_gbp(native_price, ev.currency)
                ev.noise_limit_db = (parse_noise(raw.noise_text or "")
                                     or CIRCUIT_STATIC_NOISE_DB.get(circuit))
                ev.sold_out = raw.sold_out
                ev.spaces_left = raw.spaces_left
                ev.stock_status = raw.stock_status
                ev.notes = raw.notes
                # Infer partial-day session from title text when the scraper
                # only said "day" (or didn't say). Lots of MSV / NoLimits /
                # nurburgring_tf events are evenings/twilights/AM-only and
                # were being lumped in with full-day events.
                ev.session = _infer_session(raw.session, raw.title, raw.notes)
                ev.is_package = raw.is_package
                ev.region = raw.region or "UK"
                ev.last_seen = datetime.utcnow()
                s.add(ev)
                s.flush()  # ensure ev.id available for snapshot
                # Capture snapshot only when something changed (or first sight).
                curr = (ev.price_gbp, ev.spaces_left, ev.sold_out)
                if prev != curr:
                    s.add(EventSnapshot(
                        event_id=ev.id,
                        price_gbp=ev.price_gbp,
                        spaces_left=ev.spaces_left,
                        sold_out=ev.sold_out,
                    ))
                n += 1
            s.commit()
        run.ok = True
        # Prune stale upcoming events for this source — anything that was
        # in the DB but didn't appear in the last N days of scrapes is
        # probably a ghost (organiser removed it from their listing) and
        # should drop from our display.
        if n >= MIN_EVENTS_TO_PRUNE:
            _prune_stale(event_source)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        run.error = err
    finally:
        run.n_events = n
        run.finished_at = datetime.utcnow()
        with session() as s:
            s.add(run)
            s.commit()
    return n, err


async def run_all() -> dict[str, tuple[int, str | None]]:
    init_db()
    results: dict[str, tuple[int, str | None]] = {}
    for slug in SCRAPERS:
        results[slug] = await run_one(slug)
    return results


def run_all_sync() -> dict[str, tuple[int, str | None]]:
    return asyncio.run(run_all())
