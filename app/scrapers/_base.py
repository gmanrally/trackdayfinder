"""Shared helpers for scrapers."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import httpx
from selectolax.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; TrackdayFinder/0.1; personal use)"


@dataclass
class RawEvent:
    organiser: str
    source: str
    circuit_raw: str
    event_date: date
    booking_url: str
    title: Optional[str] = None
    price_text: Optional[str] = None
    noise_text: Optional[str] = None
    vehicle_type: Optional[str] = None
    group_level: Optional[str] = None
    spaces_text: Optional[str] = None
    sold_out: bool = False
    spaces_left: Optional[int] = None
    stock_status: Optional[str] = None
    notes: Optional[str] = None
    session: Optional[str] = None       # day / evening / am / pm / am_pm
    external_id: Optional[str] = None   # source-side id (SKU, slug) — used for dedup
    currency: str = "GBP"               # ISO of price_text (GBP / EUR)
    is_package: bool = False            # bundles travel/accommodation
    region: str = "UK"                  # "UK" or "EU"


# A 429 is the one HTTP status that is not a refusal. A 403 means "not you,
# ever", and retrying it is rude; a 429 means "not now, try again", usually
# with a Retry-After saying when. Shopify sends it on /products.json when a
# shop is polled hard, and two shops spent roughly a day each failing on it
# because nothing here waited and tried again.
RETRY_STATUSES = frozenset({429, 503})
RETRY_BACKOFF = (3.0, 12.0)         # used when the server names no delay
MAX_RETRY_AFTER = 60.0              # never sit on a scrape longer than this


async def _sleep_for(resp: httpx.Response, attempt: int) -> bool:
    """Honour Retry-After when the server sends one, else back off. Returns
    False when the wait asked for is too long to be worth holding the run."""
    raw = (resp.headers.get("retry-after") or "").strip()
    delay = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
    if raw.isdigit():
        delay = float(raw)
    if delay > MAX_RETRY_AFTER:
        return False
    await asyncio.sleep(delay)
    return True


async def get_json(url: str, timeout: float = 20.0, attempts: int = 3) -> tuple[dict, str]:
    """Fetch a JSON endpoint, waiting out a rate limit. Returns (data, text)
    so callers can still write their debug dump."""
    last: Exception | None = None
    async with httpx.AsyncClient(headers={"User-Agent": UA},
                                 follow_redirects=True, timeout=timeout) as c:
        for attempt in range(attempts):
            r = await c.get(url)
            if r.status_code in RETRY_STATUSES and attempt + 1 < attempts:
                if await _sleep_for(r, attempt):
                    continue
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last = exc
                break
            return r.json(), r.text
    raise last if last else RuntimeError(f"could not fetch {url}")


async def get_html(url: str, timeout: float = 20.0) -> HTMLParser:
    async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True, timeout=timeout) as c:
        r = await c.get(url)
        r.raise_for_status()
        return HTMLParser(r.text)


async def get_html_js(url: str, wait_selector: str | None = None, timeout: int = 30000,
                      settle_ms: int = 3000) -> HTMLParser:
    """Render with Playwright for JS-heavy pages. Lazy import so plain HTTP scrapers don't need it."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Everything after the launch runs under a finally that closes the
        # browser. page.goto() raises on a slow site, and when it did the
        # close below was skipped and the Chromium was stranded — leaving
        # async_playwright() does not reap a browser it did not launch.
        # Three scrapers timing out nightly leaked five of them, whose
        # threads then starved the container: every other scraper died on
        # "can't start new thread", so a timeout in three sources took out
        # all thirty-three.
        try:
            ctx = await browser.new_context(user_agent=UA)
            page = await ctx.new_page()
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    pass
            # Wait for network to settle, then a small extra delay to let any deferred rendering finish.
            try:
                await page.wait_for_load_state("networkidle", timeout=timeout)
            except Exception:
                pass
            if settle_ms:
                await page.wait_for_timeout(settle_ms)
            html = await page.content()
            return HTMLParser(html)
        finally:
            try:
                await browser.close()
            except Exception:
                pass
