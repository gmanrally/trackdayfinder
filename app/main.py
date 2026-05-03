from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .models import Event, ScrapeRun, init_db, session as db_session
from . import ingest

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="TrackdayFinder")
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
        if source:
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
        circuits = sorted({e.circuit for e in all_events})
        # Build (slug, display_name) pairs for the Source dropdown.
        from .scrapers import ORGANISER_DISPLAY
        source_slugs = sorted({e.source for e in all_events})
        sources = [(slug, ORGANISER_DISPLAY.get(slug, slug.replace("_", " ").title()))
                   for slug in source_slugs]
        sessions = sorted({e.session for e in all_events if e.session})
        last = s.exec(select(ScrapeRun).order_by(ScrapeRun.finished_at.desc())).first()

    return templates.TemplateResponse(request, "index.html", {
        "events": events,
        "count": len(events),
        "circuits": circuits,
        "sources": sources,
        "sessions": sessions,
        "last_run": last.finished_at.strftime("%Y-%m-%d %H:%M") if last and last.finished_at else None,
        "now_year": today.year,
        "sort": sort_key,
        "qs_no_sort": _qs_no_sort(request),
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
        },
    })


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
