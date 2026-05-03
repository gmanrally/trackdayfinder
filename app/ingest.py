"""Run scrapers and upsert results into the DB."""
from __future__ import annotations
import asyncio
from datetime import datetime
from sqlmodel import select
from .models import Event, ScrapeRun, init_db, session
from .normalise import canonical_circuit, parse_price, parse_noise, make_dedup_key
from .scrapers import SCRAPERS


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
                key = make_dedup_key(slug, circuit, raw.event_date, raw.organiser,
                                     external_id=raw.external_id, session=raw.session)
                existing = s.exec(select(Event).where(Event.dedup_key == key)).first()
                ev = existing or Event(dedup_key=key, source=slug, organiser=raw.organiser,
                                       circuit=circuit, circuit_raw=raw.circuit_raw,
                                       event_date=raw.event_date, booking_url=raw.booking_url)
                ev.circuit = circuit
                ev.circuit_raw = raw.circuit_raw
                ev.event_date = raw.event_date
                ev.booking_url = raw.booking_url
                ev.title = raw.title
                ev.vehicle_type = raw.vehicle_type or "car"
                ev.group_level = raw.group_level
                ev.price_gbp = parse_price(raw.price_text or "")
                ev.noise_limit_db = parse_noise(raw.noise_text or "")
                ev.sold_out = raw.sold_out
                ev.spaces_left = raw.spaces_left
                ev.stock_status = raw.stock_status
                ev.notes = raw.notes
                ev.session = raw.session
                ev.last_seen = datetime.utcnow()
                s.add(ev)
                n += 1
            s.commit()
        run.ok = True
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
