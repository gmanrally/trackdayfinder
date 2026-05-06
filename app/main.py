from __future__ import annotations
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .models import Event, ScrapeRun, Click, User, Watch, AlertSent, init_db, session as db_session
from . import ingest

BASE = Path(__file__).resolve().parent

CANONICAL_HOST = "https://trackdayfinder.co.uk"

# Feature flags. Hidden from public unless explicitly enabled.
ALERTS_ENABLED = os.environ.get("ALERTS_ENABLED", "").strip() == "1"


def slugify(s: str) -> str:
    """Convert a circuit / organiser name to a URL slug."""
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters["slugify"] = slugify


def _global_meta() -> dict:
    """Total upcoming events + last refresh time — exposed to every template."""
    from sqlmodel import func
    today = date.today()
    with db_session() as s:
        n = s.exec(select(func.count(Event.id)).where(Event.event_date >= today)).one()
        last = s.exec(select(ScrapeRun).order_by(ScrapeRun.finished_at.desc())).first()
    return {
        "count": n if isinstance(n, int) else (n[0] if n else 0),
        "last_run": last.finished_at.strftime("%Y-%m-%d %H:%M") if last and last.finished_at else None,
    }

templates.env.globals["global_meta"] = _global_meta
templates.env.globals["alerts_enabled"] = ALERTS_ENABLED


def _breadcrumbs(path: str) -> list[dict]:
    """Build breadcrumb trail items from a URL path. Used for both the visible
    nav.crumbs and the JSON-LD BreadcrumbList that Google reads."""
    items = [{"name": "Home", "url": "/"}]
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return items
    # Friendly labels for top-level sections
    section_labels = {
        "map": "Map", "calendar": "Calendar",
        "circuit": "Circuits", "circuits": "Circuits",
        "organiser": "Organisers", "organisers": "Organisers",
        "trackday": "Trackday",
        "alerts": "Alerts",
    }
    head = parts[0]
    items.append({"name": section_labels.get(head, head.title()),
                  "url": f"/{head}" if head not in ("circuit", "organiser", "trackday") else f"/{head}s"})
    if len(parts) > 1:
        # last segment is the entity slug — humanise it
        tail = parts[-1].replace("-", " ").replace("_", " ").title()
        items.append({"name": tail, "url": "/" + "/".join(parts)})
    return items


templates.env.globals["breadcrumbs_for"] = _breadcrumbs
templates.env.globals["canonical_host"] = CANONICAL_HOST

app = FastAPI(title="TrackdayFinder")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
scheduler = AsyncIOScheduler()


# Many scrapers (Facebook's link debugger, monitoring uptime checks, link
# previewers in Slack/iMessage etc.) probe URLs with HEAD before doing GET.
# FastAPI doesn't handle HEAD on GET routes by default and returns 405,
# which causes Facebook to report "Bad Response Code". Treat HEAD as GET
# and strip the body before sending.
@app.middleware("http")
async def head_as_get(request: Request, call_next):
    if request.method != "HEAD":
        return await call_next(request)
    request.scope["method"] = "GET"
    response = await call_next(request)
    # Empty body but keep status + headers so Content-Length stays accurate.
    from starlette.responses import Response as _R
    return _R(status_code=response.status_code, headers=dict(response.headers))


# Link-preview bots (Facebook, Twitter, LinkedIn, Slack, Discord etc.) only
# care about the <meta og:*> tags. Our index can be 1.5 MB which is over
# Facebook's OG-parse limit, so they fail to extract tags despite them
# being at the top of <head>. Serve a tiny standalone page when the UA matches.
_LINK_BOT_UA = re.compile(
    r"(facebookexternalhit|facebookcatalog|Twitterbot|LinkedInBot|Slackbot|"
    r"discordbot|WhatsApp|TelegramBot|Pinterestbot|SkypeUriPreview|"
    r"Embedly|Iframely|redditbot|vkShare|W3C_Validator|XING-contenttabreceiver|"
    r"Applebot|bingbot|Googlebot.*Snippet|Mastodon|Bluesky|google-imageproxy)",
    re.I,
)

@app.middleware("http")
async def slim_for_link_bots(request: Request, call_next):
    ua = request.headers.get("user-agent", "")
    if not _LINK_BOT_UA.search(ua):
        return await call_next(request)
    # Serve only the home/canonical page slim version. Other paths still
    # get the normal response (those have small templates anyway).
    if request.url.path not in ("/", ""):
        return await call_next(request)
    today_year = date.today().year
    canonical = f"{CANONICAL_HOST}/"
    html = f"""<!doctype html><html lang="en-GB"><head>
<meta charset="utf-8">
<title>TrackdayFinder.co.uk — Europe's largest trackday database</title>
<meta name="description" content="Europe's largest trackday database. Find car and bike trackdays across the UK and Europe — free, no sign-up.">
<link rel="canonical" href="{canonical}">

<meta property="og:site_name" content="TrackdayFinder.co.uk">
<meta property="og:type" content="website">
<meta property="og:title" content="TrackdayFinder — Europe's largest trackday database">
<meta property="og:description" content="Find car and bike trackdays across Europe. 1,600+ events, free to use, no sign-up.">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{CANONICAL_HOST}/static/og-image.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="TrackdayFinder — Europe's largest trackday database">
<meta name="twitter:description" content="Find car and bike trackdays across Europe. 1,600+ events, free to use, no sign-up.">
<meta name="twitter:image" content="{CANONICAL_HOST}/static/og-image.jpg">
</head><body>
<h1>TrackdayFinder.co.uk</h1>
<p>Europe's largest trackday database. <a href="{canonical}">Visit the site</a>.</p>
</body></html>"""
    from starlette.responses import HTMLResponse as _H
    body_bytes = html.encode("utf-8")
    return _H(body_bytes, headers={
        # `no-transform` tells nginx + any intermediary to deliver the body
        # byte-for-byte, no gzip and no chunking. Some link-preview bots
        # (notably Facebook on small responses) misparse gzipped+chunked HTML.
        "Cache-Control": "public, max-age=300, no-transform",
        "Content-Length": str(len(body_bytes)),
        "X-Accel-Buffering": "no",
    })


def _build_month_choices(events) -> list[tuple[str, str]]:
    """Return list of (value="YYYY-MM", label) for months that have at least
    one upcoming event. Labels are bare month names ("May") unless the same
    month occurs in multiple years (then "May 26" / "May 27") — keeps the chip
    bar compact while staying unambiguous."""
    months: dict[str, set[int]] = {}   # "May" -> {2026, 2027}
    keys: dict[str, str] = {}          # "2026-05" -> "May"
    for e in events:
        key = e.event_date.strftime("%Y-%m")
        name = e.event_date.strftime("%B")
        if key in keys:
            continue
        keys[key] = name
        months.setdefault(name, set()).add(e.event_date.year)
    out: list[tuple[str, str]] = []
    for k in sorted(keys):
        name = keys[k]
        years = months[name]
        if len(years) > 1:
            year_short = k.split("-")[0][-2:]
            label = f"{name[:3]} {year_short}"
        else:
            label = name
        out.append((k, label))
    return out


WEEKDAY_CHOICES = [
    ("Mon", "Mon"), ("Tue", "Tue"), ("Wed", "Wed"), ("Thu", "Thu"),
    ("Fri", "Fri"), ("Sat", "Sat"), ("Sun", "Sun"),
]


def _qs_no_sort(request: Request) -> str:
    """Current query string with the `sort` param stripped, urlencoded.
    Used by sort-link template macro so clicking a column preserves filters."""
    from urllib.parse import urlencode
    params = [(k, v) for k, v in request.query_params.multi_items() if k != "sort"]
    return urlencode(params)


# Each "page" of the index is a 30-day window.
INDEX_PAGE_DAYS = 30


def _filtered_events_query(circuit, vehicle, source, session,
                           from_, to, max_price, hide_sold_out, sort,
                           weekdays=None, month=None):
    """Build a select(Event) with all user filters + the chosen sort applied.
    Returns (query, sort_key) — caller handles execution.

    weekdays: list of 'Mon'|'Tue'|... (or 0..6 ints, Mon=0); only events whose
              `event_date.weekday()` matches will pass.
    month:    'YYYY-MM' string. Constrains to that calendar month."""
    from sqlmodel import func as _func
    today = date.today()
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
    # Month — accept "YYYY-MM"
    if month:
        try:
            y, m = month.split("-")
            y, m = int(y), int(m)
            from calendar import monthrange
            first = date(y, m, 1)
            last  = date(y, m, monthrange(y, m)[1])
            q = q.where(Event.event_date >= first, Event.event_date <= last)
        except (ValueError, IndexError):
            pass
    # Weekdays — SQLite: strftime('%w', date) gives 0..6 with 0=Sunday.
    # We accept names ('Mon'..'Sun') or ints (0=Mon..6=Sun, Python convention).
    if weekdays:
        py_to_sqlite = {0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "6", 6: "0"}
        names = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
        sqlite_codes = []
        for w in weekdays:
            w = (w or "").strip().lower()
            if w in names:
                sqlite_codes.append(py_to_sqlite[names[w]])
            elif w.isdigit() and 0 <= int(w) <= 6:
                sqlite_codes.append(py_to_sqlite[int(w)])
        if sqlite_codes:
            q = q.where(_func.strftime("%w", Event.event_date).in_(sqlite_codes))

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
    return q, sort_key


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    import os
    # No auto-scrape on boot — startup tasks silently swallow exceptions which
    # made debugging painful. Population is handled by the nightly in-process
    # cron below + the host-side cron at /etc/cron.d/trackdayfinder-refresh,
    # plus an explicit `python -m app.cli refresh` for first-boot or on demand.
    hour = int(os.environ.get("TRACKDAYFINDER_REFRESH_HOUR", "3"))
    minute = int(os.environ.get("TRACKDAYFINDER_REFRESH_MINUTE", "0"))
    scheduler.add_job(ingest.run_all, "cron", hour=hour, minute=minute, id="refresh")
    # Daily digest at 06:00 — 3 hours after the 03:00 refresh — only when
    # alerts are enabled via env var (otherwise no users to digest anyway).
    if ALERTS_ENABLED:
        digest_hour = int(os.environ.get("TRACKDAYFINDER_DIGEST_HOUR", "6"))
        digest_minute = int(os.environ.get("TRACKDAYFINDER_DIGEST_MINUTE", "0"))
        from . import alerts as _alerts
        scheduler.add_job(_alerts.run_digests, "cron", hour=digest_hour, minute=digest_minute, id="digests")
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
                sort: Optional[str] = None,
                from_offset: Optional[str] = None,
                month: Optional[str] = None):
    weekdays = request.query_params.getlist("weekdays")
    today = date.today()
    # `from_offset` is the JS pagination cursor — number of days from today
    # where the visible window starts. Default 0 → show today .. today+30d.
    try:
        offset = max(0, int(from_offset or 0))
    except ValueError:
        offset = 0
    win_start = today + timedelta(days=offset)
    win_end   = win_start + timedelta(days=INDEX_PAGE_DAYS)

    with db_session() as s:
        q, sort_key = _filtered_events_query(circuit, vehicle, source, session,
                                             from_, to, max_price, hide_sold_out, sort,
                                             weekdays=weekdays, month=month)
        # If user picked a specific month, skip the rolling 30-day window —
        # just show everything that month.
        if month:
            windowed = q
            has_more = False
        else:
            windowed = q.where(Event.event_date < win_end, Event.event_date >= win_start)
            beyond = s.exec(q.where(Event.event_date >= win_end).limit(1)).first()
            has_more = beyond is not None
        events = s.exec(windowed).all()
        # Total matching the user's filters (no pagination) — for the count pill.
        from sqlmodel import func
        total_count = s.exec(select(func.count()).select_from(q.subquery())).one()
        if isinstance(total_count, tuple):
            total_count = total_count[0]

        all_events = s.exec(select(Event).where(Event.event_date >= today)).all()

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
        months = _build_month_choices(all_events)
        last = s.exec(select(ScrapeRun).order_by(ScrapeRun.finished_at.desc())).first()

    return templates.TemplateResponse(request, "index.html", {
        "events": events,
        "count": total_count,
        "total_count": total_count,
        "has_more": has_more,
        "next_from": offset + INDEX_PAGE_DAYS,
        "circuits": circuits,
        "sources_grouped": sources_grouped,
        "sessions": sessions,
        "months": months,
        "weekday_choices": WEEKDAY_CHOICES,
        "last_run": last.finished_at.strftime("%Y-%m-%d %H:%M") if last and last.finished_at else None,
        "now_year": today.year,
        "today_iso": today.isoformat(),
        "sort": sort_key,
        "qs_no_sort": _qs_no_sort(request),
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
            "weekdays": list(weekdays),
            "month": month,
        },
    })


@app.get("/_chunk")
async def index_chunk(request: Request,
                      circuit: Optional[str] = None,
                      vehicle: Optional[str] = None,
                      source: Optional[str] = None,
                      session: Optional[str] = None,
                      from_: Optional[str] = None,
                      to: Optional[str] = None,
                      max_price: Optional[str] = None,
                      hide_sold_out: Optional[str] = None,
                      sort: Optional[str] = None,
                      from_offset: Optional[str] = None,
                      month: Optional[str] = None):
    """Returns rendered <tr>s for the next 30-day window, plus a has_more flag.
    Used by the index page's infinite-scroll JS."""
    weekdays = request.query_params.getlist("weekdays")
    today = date.today()
    try:
        offset = max(0, int(from_offset or 0))
    except ValueError:
        offset = 0
    win_start = today + timedelta(days=offset)
    win_end   = win_start + timedelta(days=INDEX_PAGE_DAYS)

    with db_session() as s:
        q, _ = _filtered_events_query(circuit, vehicle, source, session,
                                      from_, to, max_price, hide_sold_out, sort,
                                      weekdays=weekdays, month=month)
        if month:
            events = s.exec(q).all()
            has_more = False
        else:
            events = s.exec(q.where(Event.event_date < win_end,
                                    Event.event_date >= win_start)).all()
            beyond = s.exec(q.where(Event.event_date >= win_end).limit(1)).first()
            has_more = beyond is not None

    tmpl = templates.env.get_template("_event_row.html")
    html = "".join(tmpl.render(e=ev, request=request) for ev in events)
    return {
        "html": html,
        "has_more": has_more,
        "next_from": offset + INDEX_PAGE_DAYS,
    }


@app.get("/trackday/{source}/{key}", response_class=HTMLResponse)
async def event_detail(request: Request, source: str, key: str):
    """SEO-friendly per-event detail page."""
    from .models import EventSnapshot
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
        snapshots = s.exec(
            select(EventSnapshot)
            .where(EventSnapshot.event_id == e.id)
            .order_by(EventSnapshot.captured_at)
        ).all()
    history = [
        {"at": sn.captured_at.strftime("%d %b"),
         "price": sn.price_gbp,
         "spaces": sn.spaces_left,
         "sold_out": sn.sold_out}
        for sn in snapshots
    ]
    return templates.TemplateResponse(request, "event.html", {
        "e": e, "related": related, "history": history, "now_year": today.year,
    })


@app.get("/circuits", response_class=HTMLResponse)
async def circuits_index(request: Request):
    """Hub page listing every circuit (with or without current events)."""
    from .circuit_coords import CIRCUIT_COORDS
    today = date.today()
    with db_session() as s:
        events = s.exec(select(Event).where(Event.event_date >= today).order_by(Event.event_date)).all()
    by_circuit: dict[str, list] = {}
    for e in events:
        by_circuit.setdefault(e.circuit, []).append(e)

    # Crude UK/EU split — circuits in coords have known regions via the events.
    def region_of(name: str) -> str:
        evs = by_circuit.get(name, [])
        if evs:
            return "United Kingdom" if any(e.region == "UK" for e in evs) else "Europe"
        # No events — guess from EXTERNAL_REGION or coords latitude (UK roughly < 60° N, > 49° N, longitude < 2° E)
        from .circuit_coords import EXTERNAL_REGION
        if name in EXTERNAL_REGION:
            return "United Kingdom" if EXTERNAL_REGION[name] == "UK" else "Europe"
        lat, lng = CIRCUIT_COORDS.get(name, (0, 0))
        return "United Kingdom" if (49 <= lat <= 60 and -8 <= lng <= 2) else "Europe"

    rows = []
    for name in sorted(CIRCUIT_COORDS):
        evs = by_circuit.get(name, [])
        prices = [e.price_gbp for e in evs if e.price_gbp]
        rows.append({
            "name": name,
            "slug": slugify(name),
            "count": len(evs),
            "next": evs[0].event_date.strftime("%d %b") if evs else "",
            "cheapest": min(prices) if prices else None,
            "region": region_of(name),
        })
    rows.sort(key=lambda r: (-r["count"], r["name"]))
    rows_by_region = {"United Kingdom": [r for r in rows if r["region"] == "United Kingdom"],
                      "Europe":         [r for r in rows if r["region"] == "Europe"]}
    rows_by_region = {k: v for k, v in rows_by_region.items() if v}
    return templates.TemplateResponse(request, "circuits_index.html", {
        "rows": rows, "rows_by_region": rows_by_region,
        "active": sum(1 for r in rows if r["count"]),
        "now_year": today.year,
    })


@app.get("/organisers", response_class=HTMLResponse)
async def organisers_index(request: Request):
    """Hub page listing every organiser with their event count + circuit count."""
    from .scrapers import ORGANISER_DISPLAY, SOURCE_REGION
    today = date.today()
    with db_session() as s:
        events = s.exec(select(Event).where(Event.event_date >= today).order_by(Event.event_date)).all()
    by_source: dict[str, list] = {}
    for e in events:
        by_source.setdefault(e.source, []).append(e)
    rows = []
    for slug, evs in by_source.items():
        prices = [e.price_gbp for e in evs if e.price_gbp]
        rows.append({
            "name": ORGANISER_DISPLAY.get(slug, slug.replace("_", " ").title()),
            "slug": slug,
            "count": len(evs),
            "circuits": len({e.circuit for e in evs}),
            "cheapest": min(prices) if prices else None,
            "region": "United Kingdom" if SOURCE_REGION.get(slug, "UK") == "UK" else "Europe",
        })
    rows.sort(key=lambda r: (-r["count"], r["name"]))
    rows_by_region = {"United Kingdom": [r for r in rows if r["region"] == "United Kingdom"],
                      "Europe":         [r for r in rows if r["region"] == "Europe"]}
    rows_by_region = {k: v for k, v in rows_by_region.items() if v}
    return templates.TemplateResponse(request, "organisers_index.html", {
        "rows": rows, "rows_by_region": rows_by_region,
        "now_year": today.year,
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

    if matching:
        circuit_name = matching[0].circuit
    else:
        circuit_name = next((c for c in CIRCUIT_COORDS if slugify(c) == slug), None)
    if not circuit_name:
        raise HTTPException(status_code=404, detail="Circuit not found")

    # Precompute SEO stats + narrative text for this page
    seo = _circuit_seo(circuit_name, matching, organisers)

    return templates.TemplateResponse(request, "circuit.html", {
        "circuit": circuit_name,
        "events": matching,
        "organisers": organisers,
        "now_year": today.year,
        "seo": seo,
    })


def _circuit_seo(name: str, events: list, organisers: list[str]) -> dict:
    """Build search-intent title + meta description + narrative paragraphs
    using actual data so each circuit page has unique content."""
    n = len(events)
    today = date.today()
    prices = [e.price_gbp for e in events if e.price_gbp]
    cheapest = min(prices) if prices else None
    priciest = max(prices) if prices else None
    sold_out = sum(1 for e in events if e.sold_out)
    upcoming = [e for e in events if e.event_date >= today]
    next_date = upcoming[0].event_date if upcoming else None
    last_date = events[-1].event_date if events else None
    layouts = sorted({e.circuit_raw for e in events})
    noises = sorted({e.noise_limit_db for e in events if e.noise_limit_db})
    vehicle_kinds = sorted({e.vehicle_type for e in events if e.vehicle_type})
    year = today.year

    # Title for search results
    if n:
        bits = [f"{name} Trackdays {year}", f"{n} upcoming dates"]
        if cheapest:
            bits.append(f"from £{cheapest:.0f}")
        title = " · ".join(bits) + " | TrackdayFinder.co.uk"
    else:
        title = f"{name} Trackdays — schedule | TrackdayFinder.co.uk"

    # Meta description
    desc_parts = []
    if n:
        desc_parts.append(f"{n} upcoming trackdays at {name} from {len(organisers)} organisers.")
        if cheapest and priciest and cheapest != priciest:
            desc_parts.append(f"Prices £{cheapest:.0f}–£{priciest:.0f}.")
        elif cheapest:
            desc_parts.append(f"From £{cheapest:.0f}.")
        if next_date:
            desc_parts.append(f"Next session {next_date:%a %d %b %Y}.")
        desc_parts.append("Compare dates, prices and availability in one place.")
    else:
        desc_parts.append(f"Trackdays at {name}. Schedule, organisers, prices, noise limits.")
    description = " ".join(desc_parts)[:300]

    # Narrative content blocks (renders as paragraphs in the page body)
    intro = (
        f"{name} hosts {n} upcoming public trackday{'s' if n != 1 else ''} "
        f"between {next_date:%B %Y} and {last_date:%B %Y}, run by "
        f"{len(organisers)} organiser{'s' if len(organisers) != 1 else ''}: "
        f"{', '.join(organisers)}." if n else
        f"There are no scheduled public trackdays at {name} on TrackdayFinder right now."
    )

    facts = []
    if cheapest and priciest:
        if cheapest == priciest:
            facts.append(f"Prices are typically £{cheapest:.0f}.")
        else:
            facts.append(f"Prices range from £{cheapest:.0f} to £{priciest:.0f}.")
    if vehicle_kinds:
        facts.append(f"Available for {', '.join(vehicle_kinds)}.")
    if noises:
        if len(noises) == 1:
            facts.append(f"Standard noise limit is {noises[0]}dB.")
        else:
            facts.append(f"Noise limits vary by organiser ({min(noises)}–{max(noises)}dB).")
    if sold_out:
        facts.append(f"{sold_out} listed event{'s are' if sold_out != 1 else ' is'} already sold out.")
    if len(layouts) > 1:
        facts.append(f"Layout variants: {', '.join(layouts[:6])}.")

    return {
        "title": title,
        "description": description,
        "intro": intro,
        "facts": facts,
        "n": n, "cheapest": cheapest, "priciest": priciest,
        "next_date": next_date, "last_date": last_date,
        "sold_out": sold_out, "vehicle_kinds": vehicle_kinds, "noises": noises,
    }


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
    organiser_name = ORGANISER_DISPLAY.get(source, source.title())
    seo = _organiser_seo(organiser_name, events, circuits)
    return templates.TemplateResponse(request, "organiser.html", {
        "source": source,
        "organiser_name": organiser_name,
        "events": events,
        "circuits": circuits,
        "now_year": today.year,
        "seo": seo,
    })


def _organiser_seo(name: str, events: list, circuits: list[str]) -> dict:
    n = len(events)
    today = date.today()
    prices = [e.price_gbp for e in events if e.price_gbp]
    cheapest = min(prices) if prices else None
    priciest = max(prices) if prices else None
    next_date = events[0].event_date if events else None
    last_date = events[-1].event_date if events else None
    vehicle_kinds = sorted({e.vehicle_type for e in events if e.vehicle_type})
    year = today.year

    if n:
        bits = [f"{name} Trackday Calendar {year}", f"{n} dates", f"{len(circuits)} circuits"]
        if cheapest:
            bits.append(f"from £{cheapest:.0f}")
        title = " · ".join(bits) + " | TrackdayFinder.co.uk"
    else:
        title = f"{name} Trackdays — calendar | TrackdayFinder.co.uk"

    desc_parts = []
    if n:
        desc_parts.append(f"{n} upcoming trackdays from {name} across {len(circuits)} circuits.")
        if cheapest and priciest and cheapest != priciest:
            desc_parts.append(f"Prices £{cheapest:.0f}–£{priciest:.0f}.")
        if next_date:
            desc_parts.append(f"Next: {next_date:%a %d %b %Y}.")
        desc_parts.append("Compare dates, prices and stock at every UK + European circuit they run.")
    else:
        desc_parts.append(f"{name} trackday schedule. Dates, circuits, prices.")
    description = " ".join(desc_parts)[:300]

    intro = (
        f"{name} runs {n} upcoming trackday{'s' if n != 1 else ''} "
        f"between {next_date:%B %Y} and {last_date:%B %Y}, across "
        f"{len(circuits)} circuit{'s' if len(circuits) != 1 else ''}: "
        f"{', '.join(circuits[:8])}{'…' if len(circuits) > 8 else ''}." if n else
        f"No upcoming trackdays from {name} listed on TrackdayFinder right now."
    )

    facts = []
    if cheapest and priciest:
        if cheapest == priciest:
            facts.append(f"All listed events are £{cheapest:.0f}.")
        else:
            facts.append(f"Entry fees range £{cheapest:.0f}–£{priciest:.0f}.")
    if vehicle_kinds:
        facts.append(f"Catering for {', '.join(vehicle_kinds)}.")
    sold_out = sum(1 for e in events if e.sold_out)
    if sold_out:
        facts.append(f"{sold_out} event{'s are' if sold_out != 1 else ' is'} already sold out — book early.")

    return {"title": title, "description": description, "intro": intro, "facts": facts,
            "n": n, "cheapest": cheapest, "priciest": priciest,
            "next_date": next_date, "last_date": last_date}


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request,
                        circuit: Optional[str] = None,
                        vehicle: Optional[str] = None,
                        source: Optional[str] = None,
                        session: Optional[str] = None,
                        from_: Optional[str] = None,
                        to: Optional[str] = None,
                        max_price: Optional[str] = None,
                        hide_sold_out: Optional[str] = None,
                        month: Optional[str] = None):
    """Month-grid calendar view of all upcoming events. Same filters as index."""
    from .scrapers import ORGANISER_DISPLAY, SOURCE_REGION
    weekdays = request.query_params.getlist("weekdays")
    today = date.today()
    # Pick an initial date for the calendar so it lands on the user's filtered
    # range. Priority: month filter > from_ filter > earliest matching event > today.
    initial_iso = today.isoformat()
    if month:
        initial_iso = f"{month}-01"
    elif from_:
        try: date.fromisoformat(from_); initial_iso = from_
        except ValueError: pass
    with db_session() as s:
        q, _ = _filtered_events_query(circuit, vehicle, source, session,
                                      from_, to, max_price, hide_sold_out, sort=None,
                                      weekdays=weekdays, month=month)
        events = s.exec(q).all()
        all_events_today = s.exec(select(Event).where(Event.event_date >= today)).all()
    # If no explicit date filter set but other filters narrow events, jump to
    # the earliest matching one so the user actually sees results immediately.
    if initial_iso == today.isoformat() and events:
        earliest = min(e.event_date for e in events)
        if earliest > today:
            initial_iso = earliest.isoformat()

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
            "url":   f"/go/{e.id}",
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
    months = _build_month_choices(all_events_today)

    return templates.TemplateResponse(request, "calendar.html", {
        "events_json": events_json,
        "now_year": today.year,
        "today_iso": today.isoformat(),
        "initial_iso": initial_iso,
        "circuits": circuits,
        "sources_grouped": sources_grouped,
        "sessions": sessions,
        "months": months,
        "weekday_choices": WEEKDAY_CHOICES,
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
            "weekdays": list(weekdays),
            "month": month,
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
                   hide_sold_out: Optional[str] = None,
                   month: Optional[str] = None):
    """Interactive map of UK + EU circuits with upcoming events.
    Honours the same filter set as the index calendar."""
    from collections import Counter
    from .circuit_coords import CIRCUIT_COORDS
    from .scrapers import ORGANISER_DISPLAY, SOURCE_REGION
    weekdays = request.query_params.getlist("weekdays")
    today = date.today()
    with db_session() as s:
        q, _ = _filtered_events_query(circuit, vehicle, source, session,
                                      from_, to, max_price, hide_sold_out, sort=None,
                                      weekdays=weekdays, month=month)
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
    months = _build_month_choices(all_events_today)

    from .circuit_coords import CIRCUIT_WEBSITES, EXTERNAL_CIRCUITS, EXTERNAL_REGION
    # External venues have no scraped events — decide if they can plausibly
    # match the active filter set. If not, hide them so the map doesn't
    # mislead the user into thinking the filter applies.
    def _external_passes(name: str) -> bool:
        # Specific source picked → external venues have no events from any source.
        if source and source not in ("region-uk", "region-eu"):
            return False
        # Region: must match if a region filter is set.
        if source == "region-uk" and EXTERNAL_REGION.get(name) != "UK": return False
        if source == "region-eu" and EXTERNAL_REGION.get(name) != "EU": return False
        # Specific circuit picked → only that circuit's external marker.
        if circuit and circuit != name: return False
        # Date / month / weekday filters set → we don't know external dates;
        # hide rather than mislead.
        if from_ or to or month: return False
        if weekdays: return False
        # Vehicle: external venues run mixed; pass.
        return True
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
                "url": f"/go/{e.id}",
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
            if _external_passes(circuit_name):
                external_points.append(marker)
            # else: silently drop — filter wouldn't realistically include them
        elif n > 0:
            points.append(marker)
        else:
            # Same logic for greyed-out inactive markers: if a specific source
            # or circuit-restricting filter is on, hide them too.
            if source and source not in ("region-uk", "region-eu"):
                continue
            if circuit and circuit != circuit_name:
                continue
            if from_ or to or month or weekdays:
                continue
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
        "months": months,
        "weekday_choices": WEEKDAY_CHOICES,
        "filters": {
            "circuit": circuit, "vehicle": vehicle, "source": source, "session": session,
            "from_": from_, "to": to, "max_price": max_price,
            "hide_sold_out": bool(hide_sold_out),
        },
    })


# ============ Email alerts ============

@app.get("/alerts", response_class=HTMLResponse)
async def alerts_signup(request: Request):
    if not ALERTS_ENABLED: raise HTTPException(status_code=404)
    """Landing/signup page — pick what to watch + enter email."""
    today = date.today()
    with db_session() as s:
        rows = s.exec(select(Event).where(Event.event_date >= today)).all()
    circuits = sorted({e.circuit for e in rows})
    from .scrapers import ORGANISER_DISPLAY, SOURCE_REGION
    source_slugs = sorted({e.source for e in rows})
    sources_grouped = [
        ("UK organisers", [(s, ORGANISER_DISPLAY.get(s, s)) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "UK"]),
        ("European",      [(s, ORGANISER_DISPLAY.get(s, s)) for s in source_slugs if SOURCE_REGION.get(s, "UK") == "EU"]),
    ]
    sources_grouped = [g for g in sources_grouped if g[1]]
    return templates.TemplateResponse(request, "alerts/signup.html", {
        "circuits": circuits, "sources_grouped": sources_grouped,
        "now_year": today.year, "submitted": False,
    })


@app.post("/alerts", response_class=HTMLResponse)
async def alerts_submit(request: Request):
    if not ALERTS_ENABLED: raise HTTPException(status_code=404)
    from .alerts import get_or_create_user, add_watch, send_confirmation
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    if "@" not in email or "." not in email:
        return HTMLResponse("<p>Invalid email. <a href='/alerts'>Try again</a>.</p>", status_code=400)
    circuits = form.getlist("circuit")
    sources  = form.getlist("source")
    events   = form.getlist("event")           # one or more Event.id values
    if not circuits and not sources and not events:
        return HTMLResponse("<p>Pick at least one circuit, organiser, or event. <a href='/alerts'>Back</a>.</p>", status_code=400)

    user, created = get_or_create_user(email)
    for c in circuits:
        add_watch(user.id, "circuit", c)
    for s_ in sources:
        add_watch(user.id, "source", s_)
    # Event watches: validate each id exists, take its title for the summary.
    event_titles: list[str] = []
    if events:
        with db_session() as ses:
            for ev_id in events:
                if not ev_id.isdigit():
                    continue
                ev = ses.exec(select(Event).where(Event.id == int(ev_id))).first()
                if not ev:
                    continue
                add_watch(user.id, "event", ev_id)
                event_titles.append(f"{ev.event_date:%d %b %Y} · {ev.circuit}")

    parts = []
    if circuits:
        parts.append("Circuits: " + ", ".join(circuits))
    if sources:
        parts.append("Organisers: " + ", ".join(sources))
    if event_titles:
        parts.append("Events: " + " · ".join(event_titles))
    send_confirmation(user, " · ".join(parts))

    today = date.today()
    return templates.TemplateResponse(request, "alerts/submitted.html", {
        "email": email, "now_year": today.year,
    })


@app.get("/alerts/confirm/{token}", response_class=HTMLResponse)
async def alerts_confirm(request: Request, token: str):
    if not ALERTS_ENABLED: raise HTTPException(status_code=404)
    from .alerts import find_user_by_token
    user = find_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid or expired link")
    with db_session() as s:
        u = s.exec(select(User).where(User.id == user.id)).first()
        u.confirmed = True
        s.commit()
    return templates.TemplateResponse(request, "alerts/confirmed.html", {
        "user": user, "now_year": date.today().year,
    })


@app.get("/alerts/manage/{token}", response_class=HTMLResponse)
async def alerts_manage(request: Request, token: str):
    if not ALERTS_ENABLED: raise HTTPException(status_code=404)
    from .alerts import find_user_by_token
    user = find_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid link")
    with db_session() as s:
        watches = s.exec(select(Watch).where(Watch.user_id == user.id)).all()
        # Resolve event watches to readable titles
        event_titles: dict[str, str] = {}
        for w in watches:
            if w.kind == "event" and w.value.isdigit():
                ev = s.exec(select(Event).where(Event.id == int(w.value))).first()
                if ev:
                    event_titles[w.value] = f"{ev.event_date:%d %b %Y} · {ev.circuit} · {ev.organiser}"
    return templates.TemplateResponse(request, "alerts/manage.html", {
        "user": user, "watches": watches, "event_titles": event_titles,
        "now_year": date.today().year,
    })


@app.post("/alerts/manage/{token}/remove/{watch_id}")
async def alerts_remove_watch(request: Request, token: str, watch_id: int):
    if not ALERTS_ENABLED: raise HTTPException(status_code=404)
    from .alerts import find_user_by_token, remove_watch
    from starlette.responses import RedirectResponse
    user = find_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404)
    remove_watch(watch_id, user.id)
    return RedirectResponse(f"/alerts/manage/{token}", status_code=303)


@app.get("/alerts/unsubscribe/{token}", response_class=HTMLResponse)
async def alerts_unsubscribe(request: Request, token: str):
    if not ALERTS_ENABLED: raise HTTPException(status_code=404)
    from .alerts import find_user_by_token
    user = find_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404)
    with db_session() as s:
        u = s.exec(select(User).where(User.id == user.id)).first()
        # Delete watches; keep user row for audit but mark unconfirmed.
        for w in s.exec(select(Watch).where(Watch.user_id == user.id)).all():
            s.delete(w)
        u.confirmed = False
        s.commit()
    return templates.TemplateResponse(request, "alerts/unsubscribed.html", {
        "now_year": date.today().year,
    })


@app.get("/favicon.ico")
async def favicon_legacy():
    """Legacy /favicon.ico — used by Google's favicon crawler if a real ICO
    is dropped at /static/favicon.ico we serve that, otherwise fall back to
    the square SVG (modern browsers can handle either)."""
    from starlette.responses import FileResponse, RedirectResponse
    ico = BASE / "static" / "favicon.ico"
    png = BASE / "static" / "favicon-192.png"
    if ico.exists():
        return FileResponse(ico, media_type="image/vnd.microsoft.icon")
    if png.exists():
        return FileResponse(png, media_type="image/png")
    return RedirectResponse("/static/logo-square.svg", status_code=302)


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


@app.get("/go/{event_id}")
async def click_through(request: Request, event_id: int):
    """Logged redirect to the organiser's booking page. Records click then 302s."""
    from starlette.responses import RedirectResponse
    with db_session() as s:
        ev = s.exec(select(Event).where(Event.id == event_id)).first()
        if not ev:
            raise HTTPException(status_code=404, detail="Event not found")
        s.add(Click(
            event_id=event_id,
            source=ev.source,
            circuit=ev.circuit,
            referrer=request.headers.get("referer"),
            user_agent=(request.headers.get("user-agent") or "")[:200],
        ))
        s.commit()
        target = ev.booking_url
    return RedirectResponse(target, status_code=302)


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
