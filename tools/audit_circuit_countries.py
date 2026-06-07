"""Print every circuit with upcoming events that doesn't have a country tag.
Helps keep app/circuit_countries.py current as new circuits enter the DB."""
from collections import Counter
from datetime import date
from sqlmodel import select
from app.main import db_session
from app.models import Event
from app.circuit_countries import CIRCUIT_COUNTRY


def main() -> int:
    with db_session() as s:
        rows = s.exec(select(Event).where(Event.event_date >= date.today())).all()
    missing: Counter = Counter()
    for e in rows:
        if e.circuit not in CIRCUIT_COUNTRY:
            missing[(e.circuit, e.region)] += 1
    if not missing:
        print("All circuits with upcoming events are tagged with a country.")
        return 0
    print(f"{sum(missing.values())} events across {len(missing)} untagged circuits:\n")
    for (circ, region), n in missing.most_common():
        print(f"  {n:4d}  region={region}  circuit={circ!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
