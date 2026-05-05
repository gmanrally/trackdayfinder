"""Email-alert subsystem.

Three responsibilities:
    1. Sending email — pluggable backend ("log", "smtp", "resend") via env vars.
    2. Detecting changes since each user's last digest (new events, price drops,
       sold-out flips, low-stock).
    3. Composing and dispatching a daily digest email.

Backend selection (env vars):
    EMAIL_MODE          = "log" (default) | "smtp" | "resend"
    EMAIL_FROM          = "alerts@trackdayfinder.co.uk"
    EMAIL_OVERRIDE_TO   = optional override — when set, ALL outgoing mail goes
                          to this address regardless of recipient. Use during
                          development so test-user emails don't actually mail.
    SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_TLS  (smtp mode)
    RESEND_API_KEY      (resend mode)
"""
from __future__ import annotations
import os
import secrets
import smtplib
from datetime import datetime, timedelta, date
from email.message import EmailMessage
from typing import Iterable, Optional

from sqlmodel import select, desc as sql_desc

from .models import (
    Event, EventSnapshot, User, Watch, AlertSent, session as db_session,
)


# ============ email sending ============

CANONICAL_HOST = "https://trackdayfinder.co.uk"
DEFAULT_FROM = "alerts@trackdayfinder.co.uk"


def send_mail(to: str, subject: str, html_body: str, text_body: Optional[str] = None) -> None:
    """Send (or log) one email. Honours EMAIL_OVERRIDE_TO."""
    override = os.environ.get("EMAIL_OVERRIDE_TO", "").strip()
    actual_to = override or to
    sender = os.environ.get("EMAIL_FROM", DEFAULT_FROM)
    mode = os.environ.get("EMAIL_MODE", "log").lower()

    if mode == "log":
        body = text_body or _strip_html(html_body)
        out = (f"\n=== EMAIL (log mode) ===\n"
               f"To:      {actual_to}" + (f"  (overridden from {to})\n" if override else "\n") +
               f"From:    {sender}\n"
               f"Subject: {subject}\n\n{body}\n=== /EMAIL ===\n")
        # Best-effort: tolerate cp1252 / ascii consoles (Windows dev) by
        # replacing un-encodable characters rather than throwing.
        import sys
        try:
            sys.stdout.write(out)
        except UnicodeEncodeError:
            enc = (sys.stdout.encoding or "ascii")
            sys.stdout.write(out.encode(enc, errors="replace").decode(enc, errors="replace"))
        sys.stdout.flush()
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = actual_to
    if text_body:
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
    else:
        msg.set_content(_strip_html(html_body))
        msg.add_alternative(html_body, subtype="html")

    if mode == "smtp":
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER")
        pwd  = os.environ.get("SMTP_PASS")
        use_tls = os.environ.get("SMTP_TLS", "1") != "0"
        with smtplib.SMTP(host, port, timeout=20) as srv:
            srv.ehlo()
            if use_tls:
                srv.starttls()
                srv.ehlo()
            if user:
                srv.login(user, pwd)
            srv.send_message(msg)
        return

    if mode == "resend":
        # Inline import so requests isn't a hard dependency
        import httpx
        api_key = os.environ["RESEND_API_KEY"]
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": sender, "to": [actual_to], "subject": subject,
                  "html": html_body, "text": text_body or _strip_html(html_body)},
            timeout=20,
        )
        r.raise_for_status()
        return

    raise RuntimeError(f"unknown EMAIL_MODE: {mode!r}")


def _strip_html(html: str) -> str:
    import re
    txt = re.sub(r"<[^>]+>", "", html)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


# ============ user / watch helpers ============

def make_token() -> str:
    return secrets.token_urlsafe(24)


def get_or_create_user(email: str) -> tuple[User, bool]:
    """Returns (user, was_created). Doesn't commit — caller should."""
    email = email.strip().lower()
    with db_session() as s:
        existing = s.exec(select(User).where(User.email == email)).first()
        if existing:
            return existing, False
        u = User(email=email, token=make_token())
        s.add(u)
        s.commit()
        s.refresh(u)
        return u, True


def add_watch(user_id: int, kind: str, value: str) -> None:
    if kind not in ("circuit", "source", "event"):
        raise ValueError("kind must be 'circuit', 'source', or 'event'")
    with db_session() as s:
        existing = s.exec(
            select(Watch).where(Watch.user_id == user_id, Watch.kind == kind, Watch.value == value)
        ).first()
        if existing:
            return
        s.add(Watch(user_id=user_id, kind=kind, value=value))
        s.commit()


def remove_watch(watch_id: int, user_id: int) -> None:
    with db_session() as s:
        w = s.exec(select(Watch).where(Watch.id == watch_id, Watch.user_id == user_id)).first()
        if w:
            s.delete(w)
            s.commit()


def find_user_by_token(token: str) -> Optional[User]:
    with db_session() as s:
        return s.exec(select(User).where(User.token == token)).first()


# ============ change detection ============

def changes_for_user(user: User) -> dict[str, list[Event]]:
    """Find recent changes (since last digest) matching the user's watches.
    Returns dict with keys: new, price_drop, reopened, low_stock — each a list of Events."""
    today = date.today()
    since = user.last_digest_at or (datetime.utcnow() - timedelta(days=1))
    with db_session() as s:
        watches = s.exec(select(Watch).where(Watch.user_id == user.id)).all()
        if not watches:
            return {"new": [], "price_drop": [], "reopened": [], "low_stock": []}
        circuit_watches = {w.value for w in watches if w.kind == "circuit"}
        source_watches  = {w.value for w in watches if w.kind == "source"}
        event_watches   = {int(w.value) for w in watches if w.kind == "event" and w.value.isdigit()}

        # All upcoming events matching at least one watch.
        candidates = s.exec(
            select(Event).where(Event.event_date >= today)
        ).all()
        matching = [e for e in candidates
                    if e.circuit in circuit_watches
                    or e.source in source_watches
                    or e.id in event_watches]

        # Already-sent dedup index per (event_id, kind)
        sent = s.exec(select(AlertSent).where(AlertSent.user_id == user.id)).all()
        already = {(a.event_id, a.kind) for a in sent}

        out = {"new": [], "price_drop": [], "reopened": [], "low_stock": []}
        for e in matching:
            # NEW: first ever sight of the event for this user.
            if (e.id, "new") not in already and e.first_seen >= since:
                out["new"].append(e)
                continue
            # Re-evaluate state changes via snapshot history.
            snaps = s.exec(
                select(EventSnapshot)
                .where(EventSnapshot.event_id == e.id)
                .order_by(EventSnapshot.captured_at)
            ).all()
            if len(snaps) < 2:
                continue
            prev, curr = snaps[-2], snaps[-1]
            # Price drop ≥ 5% (avoid noisy 1-quid jitter)
            if (prev.price_gbp and curr.price_gbp and
                    curr.price_gbp <= prev.price_gbp * 0.95 and
                    (e.id, f"pd_{curr.captured_at:%Y%m%d}") not in already):
                out["price_drop"].append(e)
            # Reopened: was sold out, now isn't
            if (prev.sold_out and not curr.sold_out and
                    (e.id, "reopened") not in already):
                out["reopened"].append(e)
            # Low stock warning (≤ 3 left and not previously warned)
            if (curr.spaces_left is not None and curr.spaces_left <= 3 and not curr.sold_out and
                    (e.id, "low_stock") not in already):
                out["low_stock"].append(e)
        return out


# ============ digest composition + send ============

def _event_row_html(e: Event) -> str:
    price = f"£{e.price_gbp:.0f}" if e.price_gbp else "—"
    stock = ""
    if e.sold_out:
        stock = " · <strong>Sold out</strong>"
    elif e.spaces_left is not None:
        stock = f" · {e.spaces_left} left"
    return (
        f"<li style='margin:8px 0'>"
        f"<strong>{e.event_date:%a %d %b %Y}</strong> — "
        f"{e.circuit} · {e.organiser} · {price}{stock}"
        f"<br><a href='{CANONICAL_HOST}/go/{e.id}' "
        f"style='color:#dc2626;font-weight:600'>Book →</a></li>"
    )


def compose_digest(user: User, changes: dict) -> Optional[tuple[str, str]]:
    """Return (subject, html_body) or None if nothing to send."""
    sections = []
    if changes["new"]:
        sections.append(("New trackdays matching your watch list", changes["new"]))
    if changes["price_drop"]:
        sections.append(("Price drops", changes["price_drop"]))
    if changes["reopened"]:
        sections.append(("Now available again", changes["reopened"]))
    if changes["low_stock"]:
        sections.append(("Almost full — book soon", changes["low_stock"]))
    if not sections:
        return None

    body_parts = [
        f"<p>Hi,</p>",
        f"<p>Here's what's changed on TrackdayFinder since your last digest:</p>",
    ]
    for heading, events in sections:
        body_parts.append(f"<h3 style='color:#0f172a;margin-top:18px'>{heading}</h3>")
        body_parts.append("<ul style='padding-left:18px'>")
        body_parts.extend(_event_row_html(e) for e in events[:20])
        body_parts.append("</ul>")
    manage = f"{CANONICAL_HOST}/alerts/manage/{user.token}"
    unsub = f"{CANONICAL_HOST}/alerts/unsubscribe/{user.token}"
    body_parts.append(
        f"<hr style='margin-top:24px;border:0;border-top:1px solid #e2e8f0'>"
        f"<p style='font-size:12px;color:#64748b'>"
        f"<a href='{manage}'>Manage your watches</a> · "
        f"<a href='{unsub}'>Unsubscribe</a>"
        f"</p>"
    )
    n = sum(len(s[1]) for s in sections)
    subject = f"TrackdayFinder digest — {n} update{'s' if n != 1 else ''}"
    return subject, "".join(body_parts)


def mark_sent(user_id: int, changes: dict) -> None:
    with db_session() as s:
        for kind, events in (("new", changes["new"]),
                             ("reopened", changes["reopened"]),
                             ("low_stock", changes["low_stock"])):
            for e in events:
                s.add(AlertSent(user_id=user_id, event_id=e.id, kind=kind))
        for e in changes["price_drop"]:
            tag = f"pd_{datetime.utcnow():%Y%m%d}"
            s.add(AlertSent(user_id=user_id, event_id=e.id, kind=tag))
        s.commit()


def run_digests() -> int:
    """Send a digest to every confirmed user with any pending changes.
    Returns the number of digests sent."""
    sent = 0
    with db_session() as s:
        users = s.exec(select(User).where(User.confirmed == True)).all()  # noqa: E712
    for u in users:
        changes = changes_for_user(u)
        composed = compose_digest(u, changes)
        if not composed:
            continue
        subject, html = composed
        try:
            send_mail(u.email, subject, html)
            mark_sent(u.id, changes)
            with db_session() as s:
                u2 = s.exec(select(User).where(User.id == u.id)).first()
                u2.last_digest_at = datetime.utcnow()
                s.commit()
            sent += 1
        except Exception as exc:
            print(f"[alerts] failed to send digest to {u.email}: {exc}")
    return sent


# ============ confirmation email ============

def send_confirmation(user: User, watches_summary: str) -> None:
    confirm = f"{CANONICAL_HOST}/alerts/confirm/{user.token}"
    manage  = f"{CANONICAL_HOST}/alerts/manage/{user.token}"
    html = f"""
    <p>Hi,</p>
    <p>You asked TrackdayFinder.co.uk to alert you about:</p>
    <p style='padding:8px 12px;background:#fef2f2;border-left:3px solid #dc2626'>{watches_summary}</p>
    <p>To start receiving alerts, click below to confirm your email:</p>
    <p><a href='{confirm}' style='display:inline-block;padding:10px 18px;
       background:#dc2626;color:#fff;text-decoration:none;border-radius:6px;
       font-weight:600'>Confirm and start alerts</a></p>
    <p style='font-size:12px;color:#64748b'>If you didn't sign up, ignore this — no alerts will be sent.</p>
    <hr style='margin-top:18px;border:0;border-top:1px solid #e2e8f0'>
    <p style='font-size:12px;color:#64748b'>Manage your watches anytime:
       <a href='{manage}'>{manage}</a></p>
    """
    send_mail(user.email, "Confirm your TrackdayFinder alerts", html)
