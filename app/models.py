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
    price_gbp: Optional[float] = None        # canonical / converted price for sort/filter
    price_native: Optional[float] = None      # original price as scraped
    currency: str = Field(default="GBP")      # ISO of price_native ("GBP"/"EUR")
    spaces_left: Optional[int] = None
    sold_out: bool = False
    stock_status: Optional[str] = None        # "Low Stock", "7 Places Left", "Sold Out"
    is_package: bool = Field(default=False, index=True)
    region: str = Field(default="UK", index=True)  # "UK" or "EU"
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


class EventSnapshot(SQLModel, table=True):
    """Daily snapshot of an event's price + spaces, captured each ingest run.
    Fuels the per-event price-history sparkline + future "price drop" alerts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(index=True)
    captured_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    price_gbp: Optional[float] = None
    spaces_left: Optional[int] = None
    sold_out: bool = False


class User(SQLModel, table=True):
    """A subscriber to email alerts. Magic-link auth, no password."""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    confirmed: bool = Field(default=False)
    token: str = Field(index=True, unique=True)   # opaque secret for manage/unsub links
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_digest_at: Optional[datetime] = None


class Watch(SQLModel, table=True):
    """One thing a user wants alerts about: a circuit or an organiser source."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    kind: str = Field(index=True)         # "circuit" | "source"
    value: str = Field(index=True)        # e.g. "Donington Park" or "javelin"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AlertSent(SQLModel, table=True):
    """Dedup: once we tell user X about event Y, don't tell them again
    (unless price changes — recorded as a separate kind)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    event_id: int = Field(index=True)
    kind: str = Field(index=True)         # "new" | "price_drop" | "reopened" | "low_stock"
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class Click(SQLModel, table=True):
    """Each Book-button click — fed by the /go/<event_id> redirect."""
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(index=True)                # Event.id
    source: str = Field(index=True)                  # denormalised for fast group-by
    circuit: str = Field(index=True)
    clicked_at: datetime = Field(default_factory=datetime.utcnow)
    referrer: Optional[str] = None
    user_agent: Optional[str] = None


class Listing(SQLModel, table=True):
    """A trackday space a seller can't use and wants to pass on. TrackdayFinder
    is a noticeboard only — money + the organiser name-change happen between
    buyer and seller. Lifecycle: pending (email unverified) → active →
    sold / expired (event date passed)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # What's for sale
    circuit: str = Field(index=True)                 # canonical circuit name
    event_date: date = Field(index=True)
    organiser: Optional[str] = None                  # free text or display name
    event_id: Optional[int] = Field(default=None, index=True)  # linked Event.id if matched
    # Money
    asking_price_gbp: Optional[float] = None
    original_price_gbp: Optional[float] = None
    currency: str = Field(default="GBP")
    # The important caveat — can the organiser actually transfer the entry?
    transferable: str = Field(default="unsure")      # "yes" | "no" | "unsure"
    # Seller. Contact details are never displayed — buyers reach sellers via
    # relayed intro email (ContactRequest), so there's nothing to harvest.
    seller_email: str = Field(index=True)
    seller_name: Optional[str] = None
    note: Optional[str] = None
    # Ticked "email me about this circuit" on the form; acted on at verify
    # time (once the email is proven) by creating a confirmed User + Watch.
    alerts_opt_in: bool = Field(default=False)
    # Lifecycle
    status: str = Field(default="pending", index=True)  # pending|active|sold|expired|removed
    verify_token: str = Field(index=True)            # magic link to publish
    manage_token: str = Field(index=True)            # seller self-manage (sold/delete)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    verified_at: Optional[datetime] = None


class ContactRequest(SQLModel, table=True):
    """One buyer→seller intro email, relayed by us with Reply-To the buyer.
    Seller replies from their own inbox and chooses what to share — contact
    details never render on the site. Doubles as the rate-limit ledger."""
    id: Optional[int] = Field(default=None, primary_key=True)
    listing_id: int = Field(index=True)
    buyer_user_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    return Session(engine)
