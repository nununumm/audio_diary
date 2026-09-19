"""Single-user authentication via a signed session cookie.

This is intentionally simple: one shared password (from DIARY_PASSWORD) grants
access, and a signed, time-limited cookie keeps the session. Meant to run
behind Tailscale + HTTPS, not exposed raw to the internet.
"""
from __future__ import annotations

import hmac

from fastapi import Cookie, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import get_settings

COOKIE_NAME = "diary_session"
MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="diary-session")


def check_password(password: str) -> bool:
    """Constant-time comparison against the configured password."""
    expected = get_settings().password
    return hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def issue_cookie_value() -> str:
    return _serializer().dumps({"authed": True})


def verify_cookie_value(value: str) -> bool:
    try:
        data = _serializer().loads(value, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return bool(data.get("authed"))


def require_auth(diary_session: str | None = Cookie(default=None)) -> None:
    """FastAPI dependency that rejects unauthenticated requests."""
    if not diary_session or not verify_cookie_value(diary_session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
