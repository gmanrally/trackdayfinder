from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .models import Event, ScrapeRun, init_db, session as db_session
from . import ingest

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="TrackdayFinder")
scheduler = AsyncIOScheduler()


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
                hide_sold_out: Optional[str] = None):
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
        q = q.order_by(Event.event_date)
        events = s.exec(q).all()

        all_events = s.exec(select(Event).where(Event.event_date >= today)).all()
        circuits = sorted({e.circuit for e in all_events})
        sources = sorted({e.source for e in all_events})
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
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
        },
    })


@app.post("/refresh")
async def refresh():
    await ingest.run_all()
    return RedirectResponse("/", status_code=303)


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
