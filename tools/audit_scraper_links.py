"""Fetch each event's booking URL and check the event_date actually
appears on the page. This is the most honest way to validate scrapers —
if our row says 12 December 2026 but the page doesn't mention that
date in any common format, the scraper is wrong or the event is gone.

Usage on the VPS:
    docker compose exec -T app bash -lc 'cd /app && python tools/audit_scraper_links.py'

Options:
    --per-source N    sample at most N events per source (default 40)
    --source SLUG     restrict to a single source slug
    --concurrency N   parallel HTTP requests (default 10)
    --timeout S       per-request timeout seconds (default 12)
    --strict          don't accept the month-only fallback

Output: per-source { confirmed / date_missing / unreachable / aggregator }
plus a list of the first 20 suspicious events per source so they can be
inspected.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date as _date
from typing import Optional
import httpx
from sqlmodel import select
from app.main import db_session
from app.models import Event

UA = "Mozilla/5.0 (TrackdayFinder scraper validator)"

# Booking URLs that point to a bare organiser/site root are aggregator
# fallbacks — we can't verify dates on them.
HOMEPAGE_RE = re.compile(r"^https?://[^/]+/?$", re.I)

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
MONTH_ABBR = [m[:3] for m in MONTH_NAMES]


def _date_strings(d: _date) -> list[str]:
    """All common ways the event date might be written on the page."""
    day = d.day
    yr = d.year
    mo = d.month
    month_full = MONTH_NAMES[mo - 1]
    month_abbr = MONTH_ABBR[mo - 1]
    ordinal = "th"
    if day % 10 == 1 and day % 100 != 11: ordinal = "st"
    elif day % 10 == 2 and day % 100 != 12: ordinal = "nd"
    elif day % 10 == 3 and day % 100 != 13: ordinal = "rd"
    return [
        d.isoformat(),                                # 2026-12-12
        f"{day:02d}/{mo:02d}/{yr}",                   # 12/12/2026
        f"{day:02d}-{mo:02d}-{yr}",                   # 12-12-2026
        f"{day}/{mo}/{yr}",
        f"{day} {month_full} {yr}",                   # 12 December 2026
        f"{day} {month_abbr} {yr}",                   # 12 dec 2026
        f"{day}{ordinal} {month_full} {yr}",          # 12th December 2026
        f"{day}{ordinal} {month_abbr} {yr}",          # 12th dec 2026
        f"{month_full} {day}, {yr}",                  # December 12, 2026
        f"{month_full} {day}",                        # December 12 (no year)
        f"{day:02d}{mo:02d}{yr}",                     # 12122026
    ]


def _month_strings(d: _date) -> list[str]:
    """Used as a softer fallback: the month + year appearing on the page
    is weak evidence the event exists at all in that month."""
    return [
        f"{MONTH_NAMES[d.month - 1]} {d.year}",
        f"{MONTH_ABBR[d.month - 1]} {d.year}",
    ]


async def _check_one(client: httpx.AsyncClient, ev: Event, strict: bool, timeout: float):
    url = (ev.booking_url or "").strip()
    if not url:
        return ev, "no_url"
    if HOMEPAGE_RE.match(url):
        return ev, "aggregator"
    try:
        r = await client.get(url, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": UA})
    except (httpx.RequestError, httpx.TimeoutException, ValueError):
        return ev, "unreachable"
    if r.status_code >= 400:
        return ev, "unreachable"
    body = (r.text or "").lower()
    if not body:
        return ev, "unreachable"
    if any(s.lower() in body for s in _date_strings(ev.event_date)):
        return ev, "confirmed"
    if not strict and any(s.lower() in body for s in _month_strings(ev.event_date)):
        return ev, "month_only"
    return ev, "date_missing"


async def main_async(args) -> int:
    today = _date.today()
    with db_session() as s:
        rows = s.exec(select(Event).where(Event.event_date >= today)).all()
    if args.source:
        rows = [e for e in rows if e.source == args.source]

    by_source: dict[str, list[Event]] = defaultdict(list)
    for e in rows:
        by_source[e.source].append(e)

    sample: list[Event] = []
    for src, evs in by_source.items():
        evs = list(evs)
        random.seed(args.seed)
        random.shuffle(evs)
        sample.extend(evs[: args.per_source])

    print(f"Auditing {len(sample)} events across {len(by_source)} sources "
          f"(up to {args.per_source} per source) ...\n", flush=True)

    sem = asyncio.Semaphore(args.concurrency)

    async def _bounded(client, ev):
        async with sem:
            return await _check_one(client, ev, args.strict, args.timeout)

    results: list[tuple[Event, str]] = []
    async with httpx.AsyncClient() as client:
        chunk = 50
        for i in range(0, len(sample), chunk):
            batch = sample[i : i + chunk]
            results.extend(await asyncio.gather(*(_bounded(client, ev) for ev in batch)))
            print(f"  {i + len(batch)}/{len(sample)} checked ...", flush=True)

    per_src: dict[str, Counter] = defaultdict(Counter)
    suspicious: dict[str, list[Event]] = defaultdict(list)
    for ev, status in results:
        per_src[ev.source][status] += 1
        if status in ("date_missing", "unreachable"):
            suspicious[ev.source].append(ev)

    # ===== Per-source summary =====
    print("\nSummary (confirmed / month_only / date_missing / unreachable / aggregator / no_url):")
    print("-" * 100)
    sources = sorted(per_src.keys())
    for src in sources:
        c = per_src[src]
        total = sum(c.values())
        conf = c.get("confirmed", 0)
        mo = c.get("month_only", 0)
        miss = c.get("date_missing", 0)
        unr = c.get("unreachable", 0)
        agg = c.get("aggregator", 0)
        nou = c.get("no_url", 0)
        conf_pct = (conf * 100 / max(1, total - agg - nou)) if total > agg + nou else 0
        flag = "  " if conf_pct >= 80 or total - agg - nou == 0 else " !"
        print(f"{flag} {src:22s}  n={total:4d}  confirmed={conf:3d} ({conf_pct:5.1f}%)  "
              f"month_only={mo:3d}  MISSING={miss:3d}  unreachable={unr:3d}  "
              f"aggregator={agg:3d}  no_url={nou:3d}")

    # ===== Worst-offender details =====
    print("\nSuspicious events (date_missing or unreachable) — first 8 per source:\n")
    for src in sorted(suspicious.keys(), key=lambda s: -len(suspicious[s])):
        evs = suspicious[src][:8]
        if not evs: continue
        print(f"--- {src} ({len(suspicious[src])} flagged in sample) ---")
        for e in evs:
            print(f"   {e.event_date}  {e.circuit:25s}  {(e.organiser or '').strip()[:30]:30s}  "
                  f"url={(e.booking_url or '')[:75]}")
        print()
    return 0


def main() -> int:
    # Env-var fallbacks so the stdin-pipe invocation (which can't pass argv)
    # can still tune behaviour:
    #   TDF_AUDIT_PER_SOURCE=0  → audit every event in every source (default)
    #   TDF_AUDIT_PER_SOURCE=40 → sample 40 per source
    #   TDF_AUDIT_SOURCE=msv    → restrict to one source
    #   TDF_AUDIT_CONCURRENCY=20
    p = argparse.ArgumentParser()
    p.add_argument("--per-source", type=int,
                   default=int(os.environ.get("TDF_AUDIT_PER_SOURCE", "0")))
    p.add_argument("--source",
                   default=os.environ.get("TDF_AUDIT_SOURCE") or None)
    p.add_argument("--concurrency", type=int,
                   default=int(os.environ.get("TDF_AUDIT_CONCURRENCY", "16")))
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--strict", action="store_true")
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    if args.per_source <= 0:
        args.per_source = 10 ** 9  # effectively unbounded
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
