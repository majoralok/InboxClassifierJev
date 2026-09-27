"""Google OAuth and credential refresh helpers."""

from __future__ import annotations

import json
from typing import Any, cast

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from app.config import config
from app.database import get_user_tokens, upsert_user

GOOGLE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.modify",
)


def _client_config() -> dict[str, Any]:
    return {
        "web": {
            "client_id": config.google_client_id,
            "client_secret": config.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"{config.app_url}/api/auth/google/callback"],
        }
    }


def create_oauth_flow(state: str | None = None) -> Flow:
    return Flow.from_client_config(
        _client_config(),
        scopes=GOOGLE_SCOPES,
        state=state,
        redirect_uri=f"{config.app_url}/api/auth/google/callback",
    )


def get_authorization_url(state: str) -> str:
    url, _ = create_oauth_flow(state).authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return cast(str, url)


def credentials_to_dict(credentials: Credentials) -> dict[str, Any]:
    serialized = credentials.to_json()  # type: ignore[no-untyped-call]
    return cast(dict[str, Any], json.loads(serialized))


def exchange_authorization_code(code: str, state: str) -> tuple[str, dict[str, Any]]:
    flow = create_oauth_flow(state)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    oauth = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    profile = oauth.userinfo().get().execute()
    email = str(profile.get("email", "")).lower()
    if not email:
        raise ValueError("Google did not return an email address")
    return email, credentials_to_dict(credentials)


def get_authorized_credentials(email: str) -> Credentials:
    stored = get_user_tokens(email)
    if not stored:
        raise ValueError("Gmail is not connected")
    credentials = cast(
        Credentials,
        Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
            stored, GOOGLE_SCOPES
        ),
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())  # type: ignore[no-untyped-call]
        refreshed = credentials_to_dict(credentials)
        if not refreshed.get("refresh_token"):
            refreshed["refresh_token"] = stored.get("refresh_token")
        upsert_user(email, refreshed)
    return credentials
