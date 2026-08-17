"""Trackday-space marketplace (noticeboard).

Sellers post a space they can't use; buyers browse and contact them.
TrackdayFinder is NOT party to the transaction — money and the organiser
name-change happen between buyer and seller. This module holds the
create/verify/expire logic; it reuses alerts.py for email + tokens.

Lifecycle: pending (email unverified) → active → sold / expired.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Optional

from sqlmodel import select

from .models import Listing, Event, session as db_session
from .alerts import send_mail, make_token, CANONICAL_HOST

MARKETPLACE_FROM_NOTE = (
    "TrackdayFinder is a noticeboard only — we are not party to the sale. "
    "Always confirm with the organiser that the entry can be transferred to "
    "your name before paying."
)


def _match_event(circuit: str, event_date: date) -> Optional[int]:
    """Find a scraped Event on the same circuit + date to link the listing to."""
    with db_session() as s:
        e = s.exec(
            select(Event).where(Event.circuit == circuit, Event.event_date == event_date)
        ).first()
        return e.id if e else None


def create_listing(*, circuit: str, event_date: date, organiser: Optional[str],
                   asking_price_gbp: Optional[float], original_price_gbp: Optional[float],
                   transferable: str, seller_email: str, seller_name: Optional[str],
                   note: Optional[str]) -> Listing:
    """Create a pending listing and email the seller a verify link."""
    listing = Listing(
        circuit=circuit,
        event_date=event_date,
        organiser=organiser,
        event_id=_match_event(circuit, event_date),
        asking_price_gbp=asking_price_gbp,
        original_price_gbp=original_price_gbp,
        transferable=transferable if transferable in ("yes", "no", "unsure") else "unsure",
        seller_email=seller_email.strip().lower(),
        seller_name=seller_name,
        note=note,
        status="pending",
        verify_token=make_token(),
        manage_token=make_token(),
    )
    with db_session() as s:
        s.add(listing)
        s.commit()
        s.refresh(listing)

    _send_verify_email(listing)
    return listing


def _send_verify_email(listing: Listing) -> None:
    verify = f"{CANONICAL_HOST}/spaces/verify/{listing.verify_token}"
    price = f"£{listing.asking_price_gbp:.0f}" if listing.asking_price_gbp else "—"
    html = f"""
    <p>Thanks for listing your trackday space on TrackdayFinder.</p>
    <p><strong>{listing.circuit}</strong> — {listing.event_date:%a %d %b %Y}<br>
       Asking: {price}</p>
    <p>Click below to publish it to the board:</p>
    <p><a href="{verify}" style="background:#dc2626;color:#fff;padding:10px 18px;
       border-radius:6px;text-decoration:none;font-weight:600">Publish my listing</a></p>
    <p style="color:#64748b;font-size:13px">{MARKETPLACE_FROM_NOTE}</p>
    <p style="color:#94a3b8;font-size:12px">If you didn't create this, ignore this email.</p>
    """
    send_mail(listing.seller_email, "Confirm your trackday space listing", html)


def verify_listing(token: str) -> Optional[Listing]:
    """Publish a pending listing when its verify link is clicked."""
    with db_session() as s:
        listing = s.exec(select(Listing).where(Listing.verify_token == token)).first()
        if not listing:
            return None
        if listing.status == "pending":
            listing.status = "active"
            listing.verified_at = datetime.utcnow()
            s.add(listing)
            s.commit()
            s.refresh(listing)
        # Notify buyers watching this circuit (best-effort).
        try:
            _notify_watchers(listing)
        except Exception:
            pass
        # Send the seller their manage link now that it's live.
        _send_live_email(listing)
        return listing


def _send_live_email(listing: Listing) -> None:
    manage = f"{CANONICAL_HOST}/spaces/manage/{listing.manage_token}"
    html = f"""
    <p>Your space is now live on the TrackdayFinder board:
       <strong>{listing.circuit}</strong> — {listing.event_date:%a %d %b %Y}.</p>
    <p>Manage it here (mark as sold or remove) at any time:</p>
    <p><a href="{manage}">{manage}</a></p>
    """
    send_mail(listing.seller_email, "Your trackday space is live", html)


def set_status(manage_token: str, status: str) -> Optional[Listing]:
    """Seller action via their manage link: 'sold' or 'removed'."""
    if status not in ("sold", "removed", "active"):
        return None
    with db_session() as s:
        listing = s.exec(select(Listing).where(Listing.manage_token == manage_token)).first()
        if not listing:
            return None
        listing.status = status
        s.add(listing)
        s.commit()
        s.refresh(listing)
        return listing


def expire_past_listings() -> int:
    """Flip active listings whose event date has passed to 'expired'. Nightly."""
    today = date.today()
    n = 0
    with db_session() as s:
        stale = s.exec(select(Listing).where(
            Listing.status == "active", Listing.event_date < today
        )).all()
        for listing in stale:
            listing.status = "expired"
            s.add(listing)
            n += 1
        s.commit()
    return n


def active_listings() -> list[Listing]:
    today = date.today()
    with db_session() as s:
        return s.exec(select(Listing).where(
            Listing.status == "active", Listing.event_date >= today
        ).order_by(Listing.event_date)).all()


def past_listings(limit: int = 40) -> list[Listing]:
    """Sold / expired listings for the greyed-out archive section."""
    with db_session() as s:
        return s.exec(select(Listing).where(
            Listing.status.in_(("sold", "expired"))
        ).order_by(Listing.event_date.desc()).limit(limit)).all()


# ============ buyer → seller relay ============
#
# Contact details never render on the site. A signed-in buyer writes a message;
# we email it to the seller with Reply-To set to the buyer, and the seller
# decides whether to respond (revealing their address only then).

INTROS_PER_BUYER_PER_DAY = 5      # across the whole board
INTROS_PER_LISTING_PER_DAY = 10   # shields sellers from a flood
REPEAT_DAYS = 7                   # one intro per buyer per listing per week

MESSAGE_MAX = 1000


def send_intro(listing_id: int, buyer, message: str) -> tuple[bool, str]:
    """Relay a buyer's message to the seller. Returns (ok, user-facing text)."""
    from .models import ContactRequest
    import html as _html
    from datetime import timedelta

    message = (message or "").strip()
    if not message:
        return False, "Write a short message for the seller."
    if len(message) > MESSAGE_MAX:
        return False, f"Keep your message under {MESSAGE_MAX} characters."

    with db_session() as s:
        listing = s.exec(select(Listing).where(Listing.id == listing_id)).first()
        if not listing or listing.status != "active":
            return False, "That listing is no longer available."

        day_ago = datetime.utcnow() - timedelta(days=1)
        repeat_cutoff = datetime.utcnow() - timedelta(days=REPEAT_DAYS)
        prior = s.exec(select(ContactRequest).where(
            ContactRequest.buyer_user_id == buyer.id,
            ContactRequest.listing_id == listing_id,
            ContactRequest.created_at > repeat_cutoff,
        )).first()
        if prior:
            return False, ("You've already contacted this seller — they can reply "
                           "straight to your email.")
        sent_today = len(s.exec(select(ContactRequest).where(
            ContactRequest.buyer_user_id == buyer.id,
            ContactRequest.created_at > day_ago,
        )).all())
        if sent_today >= INTROS_PER_BUYER_PER_DAY:
            return False, "You've reached today's contact limit — try again tomorrow."
        listing_today = len(s.exec(select(ContactRequest).where(
            ContactRequest.listing_id == listing_id,
            ContactRequest.created_at > day_ago,
        )).all())
        if listing_today >= INTROS_PER_LISTING_PER_DAY:
            return False, ("This seller has had a lot of interest today — "
                           "try again tomorrow.")

        s.add(ContactRequest(listing_id=listing_id, buyer_user_id=buyer.id))
        s.commit()
        s.refresh(listing)  # commit expires attributes; reload before session closes

    safe_msg = _html.escape(message).replace("\n", "<br>")
    price = f"£{listing.asking_price_gbp:.0f}" if listing.asking_price_gbp else "—"
    html_body = f"""
    <p>A buyer on TrackdayFinder is interested in your space:</p>
    <p><strong>{listing.circuit}</strong> — {listing.event_date:%a %d %b %Y} · Asking: {price}</p>
    <div style="border-left:3px solid #dc2626;padding:8px 14px;margin:14px 0;color:#334155">
      {safe_msg}
    </div>
    <p><strong>Just reply to this email</strong> — your reply goes straight to
       {buyer.email}. We don't share your address unless you respond.</p>
    <p style="color:#64748b;font-size:13px">{MARKETPLACE_FROM_NOTE}</p>
    <p style="color:#94a3b8;font-size:12px">Getting too many messages? Mark the
       listing sold or remove it with your manage link and they'll stop.</p>
    """
    send_mail(listing.seller_email,
              f"Buyer interested in your {listing.circuit} space",
              html_body, reply_to=buyer.email)
    return True, "Message sent — the seller can reply straight to your email."


def event_ids_with_listings() -> set[int]:
    """Event.ids that have an active listing — used to badge the main list."""
    with db_session() as s:
        rows = s.exec(select(Listing.event_id).where(
            Listing.status == "active",
            Listing.event_id.is_not(None),
        )).all()
    return {r for r in rows if r}


def _notify_watchers(listing: Listing) -> None:
    """Email users watching this circuit that a space just appeared."""
    from .models import User, Watch
    with db_session() as s:
        watches = s.exec(select(Watch).where(
            Watch.kind == "circuit", Watch.value == listing.circuit
        )).all()
        user_ids = {w.user_id for w in watches}
        if not user_ids:
            return
        users = s.exec(select(User).where(User.id.in_(user_ids), User.confirmed == True)).all()  # noqa: E712
    board = f"{CANONICAL_HOST}/spaces"
    price = f"£{listing.asking_price_gbp:.0f}" if listing.asking_price_gbp else "—"
    for u in users:
        html = f"""
        <p>A trackday space just came up at a circuit you're watching:</p>
        <p><strong>{listing.circuit}</strong> — {listing.event_date:%a %d %b %Y}<br>
           Asking: {price}</p>
        <p><a href="{board}">See it on the board →</a></p>
        """
        try:
            send_mail(u.email, f"Space for sale: {listing.circuit}", html)
        except Exception:
            continue
