"""IndexNow — tell search engines about new pages the moment we find them.

One POST after each refresh gets newly-listed events crawled in hours
rather than whenever a crawler next wanders past. Bing, Yandex, Seznam
and Naver consume IndexNow and share submissions between themselves;
Google does not participate, so Google discovery still rests on
/sitemap.xml and Search Console.

Zero configuration: a key is generated once and kept in the data dir, and
served at /<key>.txt as the protocol requires. Set INDEXNOW_KEY to pin a
specific key instead.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Iterable, Optional

import httpx
from sqlmodel import select

from .models import Event, _DATA_DIR, session

ENDPOINT = "https://api.indexnow.org/indexnow"
MAX_URLS = 1000          # protocol allows 10k; stay modest and honest
_key: Optional[str] = None


def key() -> str:
    """Our IndexNow key, created on first use and reused forever after."""
    global _key
    if _key:
        return _key
    env = (os.environ.get("INDEXNOW_KEY") or "").strip()
    if env:
        _key = env
        return _key
    path = _DATA_DIR / "indexnow_key.txt"
    try:
        if path.exists():
            _key = path.read_text(encoding="utf-8").strip()
        if not _key:
            _key = secrets.token_hex(16)
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(_key, encoding="utf-8")
    except OSError:
        _key = secrets.token_hex(16)      # ephemeral; submissions still valid
    return _key


def register(app) -> str:
    """Expose /<key>.txt — how the search engines verify we own the host."""
    from fastapi.responses import PlainTextResponse
    k = key()

    async def _serve() -> PlainTextResponse:
        return PlainTextResponse(k)

    app.add_api_route(f"/{k}.txt", _serve, methods=["GET"], include_in_schema=False)
    return k


async def submit(urls: Iterable[str]) -> int:
    """Submit URLs. Returns how many were sent (0 on any failure — search
    engines never being told is a missed opportunity, not an outage)."""
    from .main import CANONICAL_HOST
    urls = [u for u in dict.fromkeys(urls) if u.startswith("http")][:MAX_URLS]
    if not urls:
        return 0
    host = CANONICAL_HOST.split("://", 1)[-1].strip("/")
    k = key()
    payload = {
        "host": host,
        "key": k,
        "keyLocation": f"{CANONICAL_HOST}/{k}.txt",
        "urlList": urls,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(ENDPOINT, json=payload,
                             headers={"Content-Type": "application/json; charset=utf-8"})
        # 200 = accepted, 202 = accepted pending key validation.
        if r.status_code in (200, 202):
            return len(urls)
    except httpx.HTTPError:
        pass
    return 0


async def submit_recent(hours: int = 26) -> int:
    """Submit the home page plus every event page first seen in the last
    `hours` — i.e. what the refresh that just ran actually added."""
    from .main import CANONICAL_HOST
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    today = datetime.utcnow().date()
    with session() as s:
        fresh = s.exec(select(Event).where(
            Event.first_seen >= cutoff, Event.event_date >= today)).all()
    urls = [f"{CANONICAL_HOST}/"]
    urls += [f"{CANONICAL_HOST}/event/{e.source}/{e.dedup_key}" for e in fresh]
    return await submit(urls)
