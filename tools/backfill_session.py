"""One-shot: re-infer session for every upcoming event using ingest._infer_session.
Safe to re-run."""
from datetime import date
from sqlmodel import select
from app.main import db_session
from app.models import Event
from app.ingest import _infer_session

def main() -> int:
    n = 0
    with db_session() as s:
        for e in s.exec(select(Event).where(Event.event_date >= date.today())).all():
            new = _infer_session(e.session, e.title, e.notes)
            if new != e.session:
                e.session = new
                s.add(e)
                n += 1
        s.commit()
    print(f"updated {n} events")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
