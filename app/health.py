"""Nightly health check — emails only when something is actually wrong.

This site is why it exists. A leaked browser starved the container until
thirty of thirty-three scrapers died on "can't start new thread", and the
worst-hit sources went four days without a successful run — while the
public pages stayed up and served stale listings throughout. Nothing
announced it. The sister site had the quieter version: one source timing
out at 02:00 six nights of eight while answering in 0.2s by day.

So this checks the three things that actually went wrong:

  * how many sources failed on their last run,
  * which sources have not succeeded in days, whatever last night said,
  * whether browsers have been left running in this container.

Silence is the healthy state: it sends nothing when there is nothing to
say. Run nightly after the refresh, and by hand with
`python -m app.cli health`.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlmodel import select

from .models import Event, ScrapeRun, session

SITE = "TrackdayFinder"
SITE_URL = "https://trackdayfinder.co.uk"

# A source that has not worked for this long is broken, not unlucky. Two
# nights can be a flaky host; three is a pattern worth a message.
STALE_DAYS = int(os.environ.get("HEALTH_STALE_DAYS", "3"))
# One or two sources failing on a given night is normal — sites go down.
# A tenth of them failing at once is the shared-cause case.
MIN_FAILURES = int(os.environ.get("HEALTH_MIN_FAILURES", "3"))
FAIL_FRACTION = float(os.environ.get("HEALTH_FAIL_FRACTION", "0.10"))
# One browser may legitimately be mid-scrape. Several are strays.
MAX_BROWSERS = int(os.environ.get("HEALTH_MAX_BROWSERS", "2"))


def _registered() -> set[str]:
    """Sources the site still scrapes.

    A retired scraper keeps its old runs in the table, and judging those
    would report it stale for ever. Only what is wired up today counts —
    and a source that emits under its own slug (an aggregator splitting
    its output) is kept too, since it has runs of its own.
    """
    from .scrapers import SCRAPERS
    return set(SCRAPERS)


def _latest_run_per_source() -> dict[str, ScrapeRun]:
    live = _registered()
    latest: dict[str, ScrapeRun] = {}
    with session() as s:
        for run in s.exec(select(ScrapeRun).order_by(ScrapeRun.started_at)).all():
            if run.source in live:
                latest[run.source] = run      # ordered, so the last one wins
    return latest


def _last_success_per_source() -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    with session() as s:
        for run in s.exec(select(ScrapeRun).where(ScrapeRun.ok == True)  # noqa: E712
                          .order_by(ScrapeRun.started_at)).all():
            out[run.source] = run.started_at
    return out


def _stray_browsers() -> int:
    """Browser processes alive in this container.

    Read from /proc rather than by shelling out, so it costs nothing and
    works in the slim container. Not available off Linux, where it simply
    reports none and the check passes.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return 0
    found = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text(errors="ignore").strip()
        except OSError:
            continue                          # process went away mid-scan
        if "chrome" in name.lower() or "firefox" in name.lower():
            found += 1
    return found


def check() -> dict:
    """What is wrong right now. `problems` empty means healthy."""
    now = datetime.utcnow()
    latest = _latest_run_per_source()
    last_ok = _last_success_per_source()
    problems: list[str] = []

    failed = sorted(slug for slug, run in latest.items() if not run.ok)
    if latest and (len(failed) >= MIN_FAILURES
                   or len(failed) >= max(1, int(len(latest) * FAIL_FRACTION))):
        problems.append(
            f"{len(failed)} of {len(latest)} sources failed on their last "
            f"run: {', '.join(failed[:12])}"
            + (" …" if len(failed) > 12 else ""))

    cutoff = now - timedelta(days=STALE_DAYS)
    stale = []
    for slug in sorted(latest):
        seen = last_ok.get(slug)
        if seen is None or seen < cutoff:
            days = "never" if seen is None else f"{(now - seen).days}d"
            stale.append(f"{slug} ({days})")
    if stale:
        problems.append(
            f"{len(stale)} sources have not succeeded in {STALE_DAYS} days: "
            + ", ".join(stale[:12]) + (" …" if len(stale) > 12 else ""))

    browsers = _stray_browsers()
    if browsers > MAX_BROWSERS:
        problems.append(
            f"{browsers} browser processes still running — a JS scrape is "
            f"leaking them, which starves the container")

    with session() as s:
        upcoming = len(s.exec(select(Event).where(
            Event.event_date >= date.today())).all())

    return {
        "site": SITE,
        "problems": problems,
        "sources": len(latest),
        "failed": failed,
        "stale": stale,
        "browsers": browsers,
        "upcoming": upcoming,
    }


def _html(report: dict) -> str:
    items = "".join(f"<li>{p}</li>" for p in report["problems"])
    return f"""
      <p>{SITE} found {len(report['problems'])} problem(s) with the
         overnight refresh.</p>
      <ul>{items}</ul>
      <p style="color:#555">{report['sources']} sources ·
         {report['upcoming']} upcoming events ·
         <a href="{SITE_URL}">{SITE_URL}</a></p>
      <p style="color:#888;font-size:12px">You only get this email when
         something is wrong. Silence means the refresh ran clean.</p>
    """


def run_and_alert() -> dict:
    """Check, and email the owner if there is anything to report."""
    report = check()
    if not report["problems"]:
        print(f"[health] {SITE}: clean — {report['sources']} sources, "
              f"{report['upcoming']} upcoming")
        return report

    summary = "; ".join(report["problems"])
    print(f"[health] {SITE}: {summary}")
    to = os.environ.get("ALERT_EMAIL", "").strip()
    if not to:
        print("[health] ALERT_EMAIL not set — not sending")
        return report
    try:
        from .alerts import send_mail
        count = len(report["problems"])
        send_mail(to, f"[{SITE}] {count} problem"
                      f"{'s' if count != 1 else ''} with the overnight refresh",
                  _html(report))
        print(f"[health] emailed {to}")
    except Exception as exc:                  # never let alerting crash the job
        print(f"[health] could not send: {type(exc).__name__}: {exc}")
    return report
