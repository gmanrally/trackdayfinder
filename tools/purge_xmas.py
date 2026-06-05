"""One-shot: delete every event on 25 December across all years. No
legitimate trackday runs on Christmas Day; these are aggregator ghosts."""
from collections import Counter
from sqlmodel import select, delete as sql_delete
from app.main import db_session
from app.models import Event


def main() -> int:
    with db_session() as s:
        rows = s.exec(select(Event).all()).all() if hasattr(select(Event), 'all') else s.exec(select(Event)).all()
        rows = [e for e in rows if e.event_date.month == 12 and e.event_date.day == 25]
        if not rows:
            print("nothing to delete")
            return 0
        by_source = Counter(e.source for e in rows)
        for src, n in by_source.most_common():
            print(f"  {n:4d}  {src}")
        for e in rows:
            s.delete(e)
        s.commit()
    print(f"deleted {len(rows)} Christmas Day events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
