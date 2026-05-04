from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import re
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .models import Event, ScrapeRun, init_db, session as db_session
from . import ingest

BASE = Path(__file__).resolve().parent

CANONICAL_HOST = "https://trackdayfinder.co.uk"


def slugify(s: str) -> str:
    """Convert a circuit / organiser name to a URL slug."""
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters["slugify"] = slugify

app = FastAPI(title="TrackdayFinder")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
scheduler = AsyncIOScheduler()


def _qs_no_sort(request: Request) -> str:
    """Current query string with the `sort` param stripped, urlencoded.
    Used by sort-link template macro so clicking a column preserves filters."""
    from urllib.parse import urlencode
    params = [(k, v) for k, v in request.query_params.multi_items() if k != "sort"]
    return urlencode(params)


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    import asyncio, os
    # If DB is empty, kick off an initial scrape in the BACKGROUND so the
    # web server starts serving immediately (otherwise nginx returns 502 for
    # the ~60s the scrape takes).
    with db_session() as s:
        if not s.exec(select(Event)).first():
            asyncio.create_task(ingest.run_all())
    # Nightly refresh at 03:00 local time (TZ from container env / OS).
    hour = int(os.environ.get("TRACKDAYFINDER_REFRESH_HOUR", "3"))
    minute = int(os.environ.get("TRACKDAYFINDER_REFRESH_MINUTE", "0"))
    scheduler.add_job(ingest.run_all, "cron", hour=hour, minute=minute, id="refresh")
    scheduler.start()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request,
                circuit: Optional[str] = None,
                vehicle: Optional[str] = None,
                source: Optional[str] = None,
                session: Optional[str] = None,
                from_: Optional[str] = None,
                to: Optional[str] = None,
                max_price: Optional[str] = None,
                hide_sold_out: Optional[str] = None,
                sort: Optional[str] = None):
    with db_session() as s:
        today = date.today()
        q = select(Event).where(Event.event_date >= today)
        if circuit:
            q = q.where(Event.circuit == circuit)
        if vehicle:
            q = q.where(Event.vehicle_type == vehicle)
        # Special region pseudo-sources from the dropdown
        if source == "region-uk":
            q = q.where(Event.region == "UK")
        elif source == "region-eu":
            q = q.where(Event.region == "EU")
        elif source:
            q = q.where(Event.source == source)
        if session:
            q = q.where(Event.session == session)
        if from_:
            try: q = q.where(Event.event_date >= date.fromisoformat(from_))
            except ValueError: pass
        if to:
            try: q = q.where(Event.event_date <= date.fromisoformat(to))
            except ValueError: pass
        max_price_f: Optional[float] = None
        if max_price:
            try:
                max_price_f = float(max_price)
                q = q.where(Event.price_gbp <= max_price_f)
            except ValueError:
                pass
        if hide_sold_out:
            q = q.where(Event.sold_out == False)  # noqa: E712
        # Sort: default by date asc; "price" = cheapest first (NULLs last);
        # "price-desc" = priciest first; "date-desc" = furthest future first.
        from sqlmodel import asc, desc as sql_desc
        sort_key = (sort or "date").lower()
        if sort_key == "price":
            q = q.order_by(Event.price_gbp.is_(None), asc(Event.price_gbp), Event.event_date)
        elif sort_key == "price-desc":
            q = q.order_by(Event.price_gbp.is_(None), sql_desc(Event.price_gbp), Event.event_date)
        elif sort_key == "date-desc":
            q = q.order_by(sql_desc(Event.event_date))
        else:
            sort_key = "date"
            q = q.order_by(Event.event_date)
        events = s.exec(q).all()

        all_events = s.exec(select(Event).where(Event.event_date >= today)).all()

        # Build the Circuit dropdown so it ONLY shows circuits that have at
        # least one event matching the *currently active* Source/Vehicle/Session
        # filters (excluding the Circuit filter itself, so the user can change it).
        def _matches_other_filters(e: Event) -> bool:
            if vehicle and e.vehicle_type != vehicle:
                return False
            if session and e.session != session:
                return False
            if source == "region-uk" and e.region != "UK":
                return False
            if source == "region-eu" and e.region != "EU":
                return False
            if source and source not in ("region-uk", "region-eu") and e.source != source:
                return False
            return True
        circuits = sorted({e.circuit for e in all_events if _matches_other_filters(e)})

        # Source dropdown grouped by region: UK organisers, then EU.
        from .scrapers import ORGANISER_DISPLAY, SOURCE_REGION
        source_slugs = sorted({e.source for e in all_events})
        def _row(slug):
            return (slug, ORGANISER_DISPLAY.get(slug, slug.replace("_", " ").title()))
        sources_grouped = [
            ("UK organisers", [_row(s) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "UK"]),
            ("European",      [_row(s) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "EU"]),
        ]
        sources_grouped = [g for g in sources_grouped if g[1]]
        sessions = sorted({e.session for e in all_events if e.session})
        last = s.exec(select(ScrapeRun).order_by(ScrapeRun.finished_at.desc())).first()

    return templates.TemplateResponse(request, "index.html", {
        "events": events,
        "count": len(events),
        "circuits": circuits,
        "sources_grouped": sources_grouped,
        "sessions": sessions,
        "last_run": last.finished_at.strftime("%Y-%m-%d %H:%M") if last and last.finished_at else None,
        "now_year": today.year,
        "today_iso": today.isoformat(),
        "sort": sort_key,
        "qs_no_sort": _qs_no_sort(request),
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
        },
    })


@app.get("/trackday/{source}/{key}", response_class=HTMLResponse)
async def event_detail(request: Request, source: str, key: str):
    """SEO-friendly per-event detail page."""
    today = date.today()
    with db_session() as s:
        e = s.exec(select(Event).where(Event.source == source, Event.dedup_key == key)).first()
        if not e:
            raise HTTPException(status_code=404, detail="Event not found")
        related = s.exec(
            select(Event)
            .where(Event.circuit == e.circuit, Event.event_date >= today, Event.dedup_key != key)
            .order_by(Event.event_date)
            .limit(8)
        ).all()
    return templates.TemplateResponse(request, "event.html", {
        "e": e, "related": related, "now_year": today.year,
    })


@app.get("/circuit/{slug}", response_class=HTMLResponse)
async def circuit_page(request: Request, slug: str):
    """SEO landing page for one circuit — all upcoming dates there."""
    from .circuit_coords import CIRCUIT_COORDS
    today = date.today()
    with db_session() as s:
        all_events = s.exec(select(Event).where(Event.event_date >= today)).all()
    matching = [e for e in all_events if slugify(e.circuit) == slug]
    matching.sort(key=lambda e: e.event_date)
    organisers = sorted({e.organiser for e in matching})

    # Use the canonical name from a matching event if we have one; otherwise
    # try the coords table (so map's grey markers still resolve to a page).
    if matching:
        circuit_name = matching[0].circuit
    else:
        circuit_name = next((c for c in CIRCUIT_COORDS if slugify(c) == slug), None)
    if not circuit_name:
        raise HTTPException(status_code=404, detail="Circuit not found")

    return templates.TemplateResponse(request, "circuit.html", {
        "circuit": circuit_name,
        "events": matching,
        "organisers": organisers,
        "now_year": today.year,
    })


@app.get("/organiser/{source}", response_class=HTMLResponse)
async def organiser_page(request: Request, source: str):
    """SEO landing page for one organiser — all their upcoming events."""
    from .scrapers import ORGANISER_DISPLAY
    today = date.today()
    with db_session() as s:
        events = s.exec(
            select(Event).where(Event.source == source, Event.event_date >= today)
            .order_by(Event.event_date)
        ).all()
    if not events:
        raise HTTPException(status_code=404, detail="Organiser not found")
    circuits = sorted({e.circuit for e in events})
    return templates.TemplateResponse(request, "organiser.html", {
        "source": source,
        "organiser_name": ORGANISER_DISPLAY.get(source, source.title()),
        "events": events,
        "circuits": circuits,
        "now_year": today.year,
    })


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request,
                        circuit: Optional[str] = None,
                        vehicle: Optional[str] = None,
                        source: Optional[str] = None,
                        session: Optional[str] = None,
                        from_: Optional[str] = None,
                        to: Optional[str] = None,
                        max_price: Optional[str] = None,
                        hide_sold_out: Optional[str] = None):
    """Month-grid calendar view of all upcoming events. Same filters as index."""
    from .scrapers import ORGANISER_DISPLAY, SOURCE_REGION
    today = date.today()
    with db_session() as s:
        q = select(Event).where(Event.event_date >= today)
        if circuit:                     q = q.where(Event.circuit == circuit)
        if vehicle:                     q = q.where(Event.vehicle_type == vehicle)
        if source == "region-uk":       q = q.where(Event.region == "UK")
        elif source == "region-eu":     q = q.where(Event.region == "EU")
        elif source:                    q = q.where(Event.source == source)
        if session:                     q = q.where(Event.session == session)
        if from_:
            try: q = q.where(Event.event_date >= date.fromisoformat(from_))
            except ValueError: pass
        if to:
            try: q = q.where(Event.event_date <= date.fromisoformat(to))
            except ValueError: pass
        if max_price:
            try: q = q.where(Event.price_gbp <= float(max_price))
            except ValueError: pass
        if hide_sold_out:
            q = q.where(Event.sold_out == False)  # noqa: E712
        events = s.exec(q.order_by(Event.event_date)).all()
        all_events_today = s.exec(select(Event).where(Event.event_date >= today)).all()

    # Build events array for FullCalendar
    events_json = []
    for e in events:
        klass = "uk" if e.region == "UK" else "eu"
        if e.source == "nurburgring_tf":
            klass = "tf"
        if e.sold_out:
            klass += " soldout"
        title = f"{e.circuit} · {e.organiser}"
        events_json.append({
            "title": title,
            "start": e.event_date.isoformat(),
            "url":   e.booking_url,
            "classNames": [c for c in klass.split() if c],
        })

    # Filter dropdown context (mirror of index)
    def _matches_other_filters(e: Event) -> bool:
        if vehicle and e.vehicle_type != vehicle: return False
        if session and e.session != session: return False
        if source == "region-uk" and e.region != "UK": return False
        if source == "region-eu" and e.region != "EU": return False
        if source and source not in ("region-uk", "region-eu") and e.source != source: return False
        return True
    circuits = sorted({e.circuit for e in all_events_today if _matches_other_filters(e)})
    source_slugs = sorted({e.source for e in all_events_today})
    def _row(slug):
        return (slug, ORGANISER_DISPLAY.get(slug, slug.replace("_", " ").title()))
    sources_grouped = [
        ("UK organisers", [_row(s) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "UK"]),
        ("European",      [_row(s) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "EU"]),
    ]
    sources_grouped = [g for g in sources_grouped if g[1]]
    sessions = sorted({e.session for e in all_events_today if e.session})

    return templates.TemplateResponse(request, "calendar.html", {
        "events_json": events_json,
        "now_year": today.year,
        "today_iso": today.isoformat(),
        "circuits": circuits,
        "sources_grouped": sources_grouped,
        "sessions": sessions,
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
        },
    })


@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request,
                   circuit: Optional[str] = None,
                   vehicle: Optional[str] = None,
                   source: Optional[str] = None,
                   session: Optional[str] = None,
                   from_: Optional[str] = None,
                   to: Optional[str] = None,
                   max_price: Optional[str] = None,
                   hide_sold_out: Optional[str] = None):
    """Interactive map of UK + EU circuits with upcoming events.
    Honours the same filter set as the index calendar."""
    from collections import Counter
    from .circuit_coords import CIRCUIT_COORDS
    from .scrapers import ORGANISER_DISPLAY, SOURCE_REGION
    today = date.today()
    with db_session() as s:
        q = select(Event).where(Event.event_date >= today)
        if circuit:
            q = q.where(Event.circuit == circuit)
        if vehicle:
            q = q.where(Event.vehicle_type == vehicle)
        if source == "region-uk":
            q = q.where(Event.region == "UK")
        elif source == "region-eu":
            q = q.where(Event.region == "EU")
        elif source:
            q = q.where(Event.source == source)
        if session:
            q = q.where(Event.session == session)
        if from_:
            try: q = q.where(Event.event_date >= date.fromisoformat(from_))
            except ValueError: pass
        if to:
            try: q = q.where(Event.event_date <= date.fromisoformat(to))
            except ValueError: pass
        if max_price:
            try: q = q.where(Event.price_gbp <= float(max_price))
            except ValueError: pass
        if hide_sold_out:
            q = q.where(Event.sold_out == False)  # noqa: E712
        events = s.exec(q).all()

        all_events_today = s.exec(select(Event).where(Event.event_date >= today)).all()

    # Build dropdown context (same shape as index)
    def _matches_other_filters(e: Event) -> bool:
        if vehicle and e.vehicle_type != vehicle: return False
        if session and e.session != session: return False
        if source == "region-uk" and e.region != "UK": return False
        if source == "region-eu" and e.region != "EU": return False
        if source and source not in ("region-uk", "region-eu") and e.source != source: return False
        return True
    circuits = sorted({e.circuit for e in all_events_today if _matches_other_filters(e)})
    source_slugs = sorted({e.source for e in all_events_today})
    def _row(slug):
        return (slug, ORGANISER_DISPLAY.get(slug, slug.replace("_", " ").title()))
    sources_grouped = [
        ("UK organisers", [_row(s) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "UK"]),
        ("European",      [_row(s) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "EU"]),
    ]
    sources_grouped = [g for g in sources_grouped if g[1]]
    sessions = sorted({e.session for e in all_events_today if e.session})

    from .circuit_coords import CIRCUIT_WEBSITES, EXTERNAL_CIRCUITS
    counts = Counter(e.circuit for e in events)
    next_dates: dict[str, str] = {}
    next_events: dict[str, list[dict]] = {}   # circuit -> up to 5 next events
    for e in sorted(events, key=lambda x: x.event_date):
        next_dates.setdefault(e.circuit, e.event_date.isoformat())
        bucket = next_events.setdefault(e.circuit, [])
        if len(bucket) < 5:
            bucket.append({
                "date": e.event_date.strftime("%a %d %b %Y"),
                "iso":  e.event_date.isoformat(),
                "title": (e.title or "Trackday")[:60],
                "organiser": e.organiser,
                "url": e.booking_url,
                "sold_out": e.sold_out,
            })
    points = []                # circuits with upcoming matches — red numbered
    external_points = []       # active venues we don't scrape — red "?" marker
    inactive_points = []       # circuits we know but have no current events — grey
    for circuit_name, (lat, lng) in CIRCUIT_COORDS.items():
        n = counts.get(circuit_name, 0)
        marker = {
            "name": circuit_name,
            "slug": slugify(circuit_name),
            "lat": lat,
            "lng": lng,
            "count": n,
            "next": next_dates.get(circuit_name, ""),
            "events": next_events.get(circuit_name, []),
            "website": CIRCUIT_WEBSITES.get(circuit_name),
        }
        if circuit_name in EXTERNAL_CIRCUITS:
            external_points.append(marker)
        elif n > 0:
            points.append(marker)
        else:
            inactive_points.append(marker)

    return templates.TemplateResponse(request, "map.html", {
        "points": points,
        "external_points": external_points,
        "inactive_points": inactive_points,
        "now_year": today.year,
        "today_iso": today.isoformat(),
        "circuits": circuits,
        "sources_grouped": sources_grouped,
        "sessions": sessions,
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
        },
    })


@app.get("/sitemap.xml")
async def sitemap():
    today = date.today()
    with db_session() as s:
        events = s.exec(select(Event).where(Event.event_date >= today)).all()
    organisers = sorted({e.source for e in events})
    circuits = sorted({slugify(e.circuit) for e in events})

    urls = [(f"{CANONICAL_HOST}/", "1.0", "daily")]
    for src in organisers:
        urls.append((f"{CANONICAL_HOST}/organiser/{src}", "0.7", "daily"))
    for c in circuits:
        urls.append((f"{CANONICAL_HOST}/circuit/{c}", "0.8", "daily"))
    for e in events:
        urls.append((f"{CANONICAL_HOST}/trackday/{e.source}/{e.dedup_key}", "0.6", "weekly"))

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, prio, freq in urls:
        body.append(f"<url><loc>{loc}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        f"Sitemap: {CANONICAL_HOST}/sitemap.xml\n"
    )


@app.get("/api/events")
async def api_events():
    with db_session() as s:
        rows = s.exec(select(Event).where(Event.event_date >= date.today()).order_by(Event.event_date)).all()
        return [r.model_dump() for r in rows]


def main():
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8766, reload=False)


if __name__ == "__main__":
    main()
