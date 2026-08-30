"""CLI: python -m app.cli {refresh [source] | audit-coords}"""
from __future__ import annotations
import asyncio
import sys
from . import ingest
from .scrapers import SCRAPERS


def _audit_coords() -> int:
    """List circuits with upcoming events that have no map coordinates yet."""
    from datetime import date
    from collections import Counter
    from sqlmodel import select
    from .models import Event, session
    from .circuit_coords import CIRCUIT_COORDS
    today = date.today()
    with session() as s:
        rows = s.exec(select(Event).where(Event.event_date >= today)).all()
    counts = Counter(e.circuit for e in rows)
    missing = [(c, n) for c, n in counts.most_common() if c not in CIRCUIT_COORDS]
    if not missing:
        print(f"OK — all {len(counts)} active circuits have coordinates.")
        return 0
    print(f"Missing coords for {len(missing)} of {len(counts)} active circuits:")
    print("Add to app/circuit_coords.py:\n")
    for c, n in missing:
        print(f'    "{c}": (LAT, LNG),  # {n} upcoming events')
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage:")
        print("  python -m app.cli refresh [source_slug]")
        print("  python -m app.cli watch-refresh")
        print("  python -m app.cli audit-coords")
        print("sources:", ", ".join(SCRAPERS))
        return 0
    cmd = argv[0]
    if cmd == "refresh":
        if len(argv) > 1:
            slug = argv[1]
            if slug not in SCRAPERS:
                print(f"unknown source '{slug}'. known: {', '.join(SCRAPERS)}")
                return 2
            n, err = asyncio.run(ingest.run_one(slug))
            print(f"{slug}: {n} events" + (f" ERROR {err}" if err else ""))
        else:
            results = asyncio.run(ingest.run_all())
            for slug, (n, err) in results.items():
                print(f"{slug}: {n} events" + (f" ERROR {err}" if err else ""))
            # Host-side cron uses this path, so submit here too — otherwise
            # only the in-process nightly job would ever ping IndexNow.
            try:
                from . import indexnow
                print(f"indexnow: submitted {asyncio.run(indexnow.submit_recent())} urls")
            except Exception as e:
                print(f"indexnow: skipped ({type(e).__name__}: {e})")
        # After every refresh, auto-list any new circuits without coords.
        print()
        _audit_coords()
        return 0
    if cmd in ("audit-coords", "audit"):
        return _audit_coords()
    if cmd == "send-digests":
        from . import alerts
        n = alerts.run_digests()
        print(f"sent {n} digest{'s' if n != 1 else ''}")
        return 0
    if cmd == "blog-import":
        if len(argv) < 2:
            print("usage: python -m app.cli blog-import <wordpress-base-url>")
            return 2
        from .models import init_db as _init
        _init()
        from . import blog as blog_mod
        n = blog_mod.import_wordpress(argv[1])
        print(f"imported {n} post{'s' if n != 1 else ''}")
        return 0
    if cmd == "watch-refresh":
        results = asyncio.run(ingest.refresh_watched())
        if not results:
            print("no confirmed watches on upcoming events — nothing to refresh")
        for slug, (n, err) in results.items():
            print(f"{slug}: {n} events" + (f" ERROR {err}" if err else ""))
        return 0
    print(f"unknown command '{cmd}'")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
