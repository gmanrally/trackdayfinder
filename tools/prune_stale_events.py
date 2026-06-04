"""One-shot: delete upcoming events whose last_seen is older than the
ingest threshold. Safe to re-run; only touches rows that haven't been
re-confirmed by a recent scrape."""
from datetime import datetime, timedelta, date
from collections import Counter
from sqlmodel import select, delete as sql_delete
from app.main import db_session
from app.models import Event
from app.ingest import STALE_PRUNE_DAYS


def main() -> int:
    cutoff = datetime.utcnow() - timedelta(days=STALE_PRUNE_DAYS)
    today = date.today()
    with db_session() as s:
        stale = s.exec(select(Event).where(
            Event.event_date >= today,
            Event.last_seen.is_not(None),
            Event.last_seen < cutoff,
        )).all()
        by_source = Counter(e.source for e in stale)
        for src, n in by_source.most_common():
            print(f"  {n:5d}  {src}")
        if not stale:
            print("nothing to prune")
            return 0
        s.exec(sql_delete(Event).where(
            Event.event_date >= today,
            Event.last_seen.is_not(None),
            Event.last_seen < cutoff,
        ))
        s.commit()
    print(f"deleted {len(stale)} stale events (last_seen older than "
          f"{STALE_PRUNE_DAYS} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
