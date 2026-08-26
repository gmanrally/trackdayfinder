"""Optional TOTP second factor on top of the magic-link auth.

The emailed sign-in / manage links are long-lived bearer tokens — anyone
holding the email holds the account. Users who enable an authenticator
app get a 6-digit challenge before a session is established or an
account-controlling page opens. Unsubscribe is deliberately NEVER gated.

TOTP is RFC 6238 over stdlib hmac — no external auth dependency. The
"this browser passed the challenge" state is a signed, expiring cookie;
the signing key comes from TDF_SECRET (falls back to a per-process
random key, which just means challenges repeat after a restart).
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from fastapi import Request

TOTP_STEP = 30
TOTP_DIGITS = 6
CHALLENGE_COOKIE = "tdf_2fa"
CHALLENGE_TTL = 12 * 3600          # re-challenge after 12h per browser

_SECRET = (os.environ.get("TDF_SECRET") or "").strip() or secrets.token_hex(32)
ISSUER = "TrackdayFinder"


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def otpauth_uri(secret: str, email: str) -> str:
    return (f"otpauth://totp/{ISSUER}:{email}?secret={secret}"
            f"&issuer={ISSUER}&digits={TOTP_DIGITS}&period={TOTP_STEP}")


def _code_at(secret: str, counter: int) -> str:
    pad = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + pad)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF)
    return f"{value % (10 ** TOTP_DIGITS):0{TOTP_DIGITS}d}"


def totp_verify(secret: str, code: str, at: Optional[float] = None) -> bool:
    """Accept the current step ±1 to absorb clock drift."""
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit():
        return False
    counter = int((at if at is not None else time.time()) // TOTP_STEP)
    return any(hmac.compare_digest(_code_at(secret, counter + d), code)
               for d in (0, -1, 1))


# ---- challenge-passed cookie (signed, expiring) ----

def _sign(payload: str) -> str:
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def challenge_cookie_value(user_id: int) -> str:
    expires = int(time.time()) + CHALLENGE_TTL
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(payload)}"


def challenge_passed(request: Request, user_id: int) -> bool:
    raw = request.cookies.get(CHALLENGE_COOKIE) or ""
    parts = raw.split(".")
    if len(parts) != 3:
        return False
    uid, expires, sig = parts
    if not (uid.isdigit() and expires.isdigit()):
        return False
    if int(uid) != user_id or int(expires) < time.time():
        return False
    return hmac.compare_digest(_sign(f"{uid}.{expires}"), sig)


def needs_challenge(request: Request, user) -> bool:
    """True when this user has TOTP enabled and this browser hasn't passed
    the challenge recently."""
    if not user or not getattr(user, "totp_enabled", False):
        return False
    return not challenge_passed(request, user.id)


def qr_svg_data_uri(uri: str) -> Optional[str]:
    """QR for the enrol page. segno is pure-python; if it's ever missing the
    page still works via the manual-entry key."""
    try:
        import io
        import segno
        buf = io.BytesIO()
        segno.make(uri).save(buf, kind="svg", scale=4, border=2)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/svg+xml;base64,{b64}"
    except Exception:
        return None
