"""Nightly health check — emails only when something is actually wrong.

This site is why it exists. A leaked browser starved the container until
thirty of thirty-three scrapers died on "can't start new thread", and the
worst-hit sources went four days without a successful run — while the
public pages stayed up and served stale listings throughout. Nothing
announced it. The sister site had the quieter version: one source timing
out at 02:00 six nights of eight while answering in 0.2s by day.

So this checks the four things that actually went wrong:

  * how many sources failed on their last run,
  * which sources have not succeeded in days, whatever last night said,
  * which sources succeed but have stopped delivering anything,
  * whether browsers have been left running in this container.

That third one was added after the worst outage yet, and it is the one
that had no symptoms. Europa rewrote its markup and dropped the
schema.org microdata its scraper keyed on; Goodwood started abbreviating
the month in its diary headings. Both kept answering 200 with a full page
of events, so both scrapers kept finishing cleanly, reporting a
successful run that found zero events, and neither of the checks above
looks at how many. Europa — the second-largest source on the site — was
dead for 20 days and Goodwood for 155 before anyone counted.

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
# Unreaped exits are survivable in ones and tens; it is the slow climb
# toward the pid ceiling that eventually takes the container down.
MAX_ZOMBIES = int(os.environ.get("HEALTH_MAX_ZOMBIES", "200"))

# Zero events is not proof of a fault. A UK club circuit finishes in
# October and may not publish next season until spring, and four of ours
# were legitimately empty on the day this check was written — Pembrey had
# run its last day of the year, No Limits' page said so in as many words.
# So "delivered nothing" is reported for everyone it applies to, with how
# long it has been true, and only becomes an email when the source was
# delivering within living memory: any retained run with events on it, or
# nothing ever delivered at all.
#
# That phrasing is deliberate, and a day threshold was tried first and
# thrown away. Any fixed number either nags all winter about circuits
# that are closed, or sits quiet long enough for a real break to waste a
# season. Asking "was this working recently?" separates the two without a
# date in it, and it stops by itself: once the run history is all zeros —
# RUN_RETENTION_DAYS, thirty — a source that is simply out of season goes
# silent, having told you once.


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


def _last_delivery_per_source() -> dict[str, datetime]:
    """When each source last put a row in the table.

    Read off Event.last_seen rather than from the run history, which keeps
    only five runs per source and thirty days — far too short to tell a
    source that has been silent since May from one that stopped last week.
    Rows themselves are never pruned once their date has passed, so this
    reaches back as far as the source has ever delivered.

    Two columns, so exec() yields tuples; a single-column select would hand
    back bare scalars instead.
    """
    from sqlalchemy import func
    with session() as s:
        rows = s.exec(select(Event.source, func.max(Event.last_seen))
                      .group_by(Event.source)).all()
    return {src: seen for src, seen in rows if seen}


def _best_run_per_source() -> dict[str, int]:
    """The most events any retained run of each source brought back.

    The run table keeps five rows per source and thirty days, so a non-zero
    figure here means "this was working lately" — which is what separates a
    scraper that has broken from a circuit that has finished for the year.
    """
    from sqlalchemy import func
    with session() as s:
        rows = s.exec(select(ScrapeRun.source, func.max(ScrapeRun.n_events))
                      .group_by(ScrapeRun.source)).all()
    return {src: (n or 0) for src, n in rows}


def _browser_procs() -> tuple[int, int]:
    """(running, zombie) browser processes in this container.

    Read from /proc rather than by shelling out, so it costs nothing and
    works in the slim container. Not available off Linux, where it reports
    none and both checks pass.

    The split matters, because the two counts mean different things and the
    first version of this conflated them and cried wolf. A *running* browser
    nobody closed is the leak this was written for. A *zombie* is a browser
    that did exit, whose parent never reaped it — PID 1 here is uvicorn, and
    python as PID 1 does not reap orphans, so every browser Playwright
    abandons leaves a permanent entry behind. Zombies hold no memory and no
    threads, so they are not an emergency, but they each hold a slot in the
    container's pid cgroup: 57 of them had accumulated against a pids.max of
    4652, and that ceiling is what the container hit the night thirty of
    thirty-three scrapers died on "can't start new thread".
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return 0, 0
    running = zombie = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text(errors="ignore").strip()
            if "chrome" not in name.lower() and "firefox" not in name.lower():
                continue
            # /proc/<pid>/stat: the comm field is parenthesised and may itself
            # contain spaces, so split after the closing bracket. State is the
            # first field that follows.
            state = (entry / "stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            continue                          # process went away mid-scan
        if state == "Z":
            zombie += 1
        else:
            running += 1
    return running, zombie


def _pids_max() -> Optional[int]:
    """The container's pid ceiling, when the cgroup exposes one."""
    for p in ("/sys/fs/cgroup/pids.max", "/sys/fs/cgroup/pids/pids.max"):
        try:
            raw = Path(p).read_text().strip()
        except OSError:
            continue
        return None if raw == "max" else int(raw)
    return None


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

    # Succeeding and delivering nothing. Measured from when the source last
    # put a row in the table, not from the run history, so the number is
    # honest about months as well as days.
    delivered = _last_delivery_per_source()
    best = _best_run_per_source()
    quiet: list[str] = []
    broken: list[str] = []
    for slug in sorted(latest):
        run = latest[slug]
        if not run.ok or (run.n_events or 0) > 0:
            continue
        seen = delivered.get(slug)
        days = None if seen is None else (now - seen).days
        quiet.append(f"{slug} ({'never' if days is None else str(days) + 'd'})")
        if seen is None or best.get(slug, 0) > 0:
            broken.append(f"{slug} ({'never delivered' if days is None else str(days) + 'd ago'})")
    if broken:
        problems.append(
            f"{len(broken)} sources were delivering events recently and now "
            f"return none, while their scrapes keep succeeding — check the "
            f"listing markup still matches: {', '.join(broken)}")

    browsers, zombies = _browser_procs()
    if browsers > MAX_BROWSERS:
        problems.append(
            f"{browsers} browser processes still running — a JS scrape is "
            f"leaking them, which starves the container")
    limit = _pids_max()
    if zombies > MAX_ZOMBIES or (limit and zombies > limit * 0.5):
        problems.append(
            f"{zombies} browser processes have exited without being reaped"
            + (f" (of {limit} pids this container may hold)" if limit else "")
            + " — PID 1 is not an init, so they accumulate until nothing new "
              "can start. Add `init: true` to the compose service")

    with session() as s:
        upcoming = len(s.exec(select(Event).where(
            Event.event_date >= date.today())).all())

    return {
        "site": SITE,
        "problems": problems,
        "sources": len(latest),
        "failed": failed,
        "stale": stale,
        "quiet": quiet,
        "browsers": browsers,
        "zombies": zombies,
        "upcoming": upcoming,
    }


def _html(report: dict) -> str:
    items = "".join(f"<li>{p}</li>" for p in report["problems"])
    # Listed whether or not it counted as a problem: the duration beside each
    # slug is what separates an out-of-season circuit from a broken parser,
    # and that judgement is the reader's to make.
    quiet = report.get("quiet") or []
    quiet_html = (
        f"<p style=\"color:#555\">Delivering no events: {', '.join(quiet)}</p>"
        if quiet else "")
    return f"""
      <p>{SITE} found {len(report['problems'])} problem(s) with the
         overnight refresh.</p>
      <ul>{items}</ul>
      {quiet_html}
      <p style="color:#555">{report['sources']} sources ·
         {report['upcoming']} upcoming events ·
         <a href="{SITE_URL}">{SITE_URL}</a></p>
      <p style="color:#888;font-size:12px">You only get this email when
         something is wrong. Silence means the refresh ran clean.</p>
    """


def run_and_alert() -> dict:
    """Check, and email the owner if there is anything to report."""
    report = check()
    if report.get("quiet"):
        print(f"[health] {SITE}: delivering no events — "
              f"{', '.join(report['quiet'])}")
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
