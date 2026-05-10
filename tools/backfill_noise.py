"""One-shot: apply CIRCUIT_STATIC_NOISE_DB to every upcoming event that
doesn't already have a noise value. Safe to re-run."""
from datetime import date
from sqlmodel import select
from app.main import db_session
from app.models import Event
from app.circuit_noise import CIRCUIT_STATIC_NOISE_DB

def main() -> int:
    n = 0
    with db_session() as s:
        for e in s.exec(select(Event).where(Event.event_date >= date.today())).all():
            if e.noise_limit_db:
                continue
            v = CIRCUIT_STATIC_NOISE_DB.get(e.circuit)
            if v:
                e.noise_limit_db = v
                s.add(e)
                n += 1
        s.commit()
    print(f"backfilled noise on {n} events")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
