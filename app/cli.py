"""CLI: python -m app.cli refresh [source]"""
from __future__ import annotations
import asyncio
import sys
from . import ingest
from .scrapers import SCRAPERS


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m app.cli refresh [source_slug]")
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
        return 0
    print(f"unknown command '{cmd}'")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
