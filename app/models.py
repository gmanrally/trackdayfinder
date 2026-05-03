from datetime import date, datetime
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session
from pathlib import Path

import os
_DATA_DIR = Path(os.environ.get("TRACKDAYFINDER_DATA") or (Path(__file__).resolve().parent.parent / "data"))
DB_PATH = _DATA_DIR / "trackdays.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    dedup_key: str = Field(index=True, unique=True)

    source: str = Field(index=True)              # organiser slug, e.g. "msv"
    organiser: str                               # display name
    circuit: str = Field(index=True)             # canonical circuit name
    circuit_raw: str                             # as scraped
    event_date: date = Field(index=True)
    vehicle_type: Optional[str] = None           # car / bike / both
    group_level: Optional[str] = None            # novice / inter / open / mixed
    session: Optional[str] = Field(default=None, index=True)  # day / evening / am / pm / am_pm
    noise_limit_db: Optional[int] = None
    price_gbp: Optional[float] = None
    spaces_left: Optional[int] = None
    sold_out: bool = False
    stock_status: Optional[str] = None   # raw badge text: "Low Stock", "7 Places Left", "Sold Out"
    booking_url: str
    title: Optional[str] = None
    notes: Optional[str] = None

    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class ScrapeRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    ok: bool = False
    n_events: int = 0
    error: Optional[str] = None


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    return Session(engine)
