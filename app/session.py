"""Signed sessions, OAuth state, and same-origin request checks."""

from __future__ import annotations

import base64
import json
import time

from fastapi import Request, Response

from app.config import config
from app.crypto import sign_value, verify_signed_value

SESSION_COOKIE = "jev_session"
OAUTH_STATE_COOKIE = "jev_oauth_state"
SESSION_SECONDS = 7 * 24 * 60 * 60


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def set_session(response: Response, email: str) -> None:
    payload = {
        "email": email.lower(),
        "exp": int(time.time() * 1000) + SESSION_SECONDS * 1000,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
    response.set_cookie(
        SESSION_COOKIE,
        sign_value(encoded),
        httponly=True,
        secure=config.production,
        samesite="lax",
        path="/",
        max_age=SESSION_SECONDS,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_session_email(request: Request) -> str | None:
    signed = request.cookies.get(SESSION_COOKIE)
    if not signed:
        return None
    try:
        encoded = verify_signed_value(signed)
        if not encoded:
            return None
        payload = json.loads(_decode(encoded))
        if (
            not payload.get("email")
            or payload.get("exp", 0) < int(time.time() * 1000)
            or payload["email"] != config.allowed_email
        ):
            return None
        return str(payload["email"])
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def assert_same_origin(request: Request) -> None:
    if request.headers.get("origin") != config.app_url:
        raise PermissionError("Invalid request origin")
