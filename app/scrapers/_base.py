"""Shared helpers for scrapers."""
from __future__ import annotations
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
