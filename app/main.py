"""FastAPI entry point for the Python Jev Inbox Classifier."""

from __future__ import annotations

import hmac
import json
import logging
import secrets
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint

from app.categories import CATEGORIES, is_category_key
from app.classifier import (
    JobAlreadyRunningError,
    apply_reviewed_category,
    run_classification_job,
)
from app.config import check_runtime_config, config
from app.database import (
    delete_user,
    get_dashboard_stats,
    get_db,
    get_last_job,
    get_user_tokens,
    list_classifications,
    upsert_user,
)
from app.email_parser import EmailContent
from app.gmail import revoke_google_token
from app.google_auth import exchange_authorization_code, get_authorization_url
from app.jev import classify_with_jev
from app.routing import route_jev_decision
from app.session import (
    OAUTH_STATE_COOKIE,
    assert_same_origin,
    clear_session,
    get_session_email,
    set_session,
)

BASE_DIR = Path(__file__).resolve().parent
MAX_JSON_BODY_BYTES = 64 * 1024
logger = logging.getLogger(__name__)
app = FastAPI(title="Jev Inbox", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


class OAuthCallbackError(ValueError):
    """A validation error that is safe to show after the OAuth redirect."""


@app.middleware("http")
async def add_security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        )
    )
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    if config.production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _json_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def _read_json_object(request: Request) -> dict[str, object]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ValueError("Content-Type must be application/json")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_JSON_BODY_BYTES:
            raise ValueError("JSON request body is too large")
        chunks.append(chunk)
    try:
        value = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Request body must contain valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")
    return value


@app.get("/")
def home(request: Request) -> Response:
    configuration_errors = check_runtime_config()
    email = None if configuration_errors else get_session_email(request)
    context = {
        "request": request,
        "configuration_errors": configuration_errors,
        "oauth_error": request.query_params.get("error"),
        "email": email,
        "categories": CATEGORIES,
        "records": list_classifications(email) if email else [],
        "stats": get_dashboard_stats(email) if email else None,
        "last_job": get_last_job() if email else None,
        "threshold": config.confidence_threshold if email else None,
    }
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/api/health")
def health() -> JSONResponse:
    if check_runtime_config():
        return JSONResponse({"status": "unhealthy", "reason": "configuration"}, status_code=503)
    try:
        get_db().one("SELECT 1 AS healthy")
        return JSONResponse({"status": "ok"})
    except Exception:
        return JSONResponse({"status": "unhealthy", "reason": "database"}, status_code=503)


@app.get("/api/auth/google/start")
def google_start() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(get_authorization_url(state), status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        secure=config.production,
        samesite="lax",
        path="/",
        max_age=10 * 60,
    )
    return response


@app.get("/api/auth/google/callback")
def google_callback(request: Request) -> RedirectResponse:
    try:
        oauth_error = request.query_params.get("error")
        if oauth_error:
            message = (
                "Google access was declined."
                if oauth_error == "access_denied"
                else "Google authorization failed."
            )
            raise OAuthCallbackError(message)
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
        if (
            not code
            or not state
            or not expected_state
            or not hmac.compare_digest(state, expected_state)
        ):
            raise OAuthCallbackError("OAuth validation failed. Please try connecting again.")
        email, tokens = exchange_authorization_code(code, state)
        if email != config.allowed_email:
            raise OAuthCallbackError(f"This app is restricted to {config.allowed_email}.")
        existing = get_user_tokens(email) or {}
        merged = {**existing, **tokens}
        merged["refresh_token"] = tokens.get("refresh_token") or existing.get("refresh_token")
        if not merged.get("refresh_token"):
            raise OAuthCallbackError(
                "Google did not provide long-term access. Revoke the app in your "
                "Google Account and connect again."
            )
        upsert_user(email, merged)
        response = RedirectResponse(config.app_url, status_code=302)
        set_session(response, email)
    except OAuthCallbackError as error:
        response = RedirectResponse(f"{config.app_url}/?error={quote(str(error))}", status_code=302)
    except Exception:
        logger.exception("Google OAuth callback failed")
        response = RedirectResponse(
            f"{config.app_url}/?error={quote('Google connection failed. Check the server logs.')}",
            status_code=302,
        )
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return response


@app.post("/api/classify")
def classify(request: Request) -> JSONResponse:
    try:
        assert_same_origin(request)
    except PermissionError as error:
        return _json_error(str(error), 403)
    email = get_session_email(request)
    if not email:
        return _json_error("Not authenticated", 401)
    try:
        return JSONResponse(run_classification_job(email, "manual"))
    except JobAlreadyRunningError as error:
        return _json_error(str(error), 409)
    except Exception as error:
        return _json_error(str(error) or "Classification failed", 500)


@app.post("/api/learn/classify")
async def classify_learning_sample(request: Request) -> JSONResponse:
    """Evaluate one sample without reading or changing Gmail."""
    try:
        assert_same_origin(request)
    except PermissionError as error:
        return _json_error(str(error), 403)
    email = get_session_email(request)
    if not email:
        return _json_error("Not authenticated", 401)

    try:
        body = await _read_json_object(request)
    except ValueError as error:
        return _json_error(str(error), 400)

    subject = body.get("subject")
    message = body.get("message")
    sender = body.get("sender", "sample@example.com")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 300:
        return _json_error("Subject must contain 1 to 300 characters", 400)
    if not isinstance(message, str) or not message.strip() or len(message) > 12_000:
        return _json_error("Message must contain 1 to 12000 characters", 400)
    if not isinstance(sender, str) or not sender.strip() or len(sender) > 320:
        return _json_error("Sender must contain 1 to 320 characters", 400)

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sample = EmailContent(
        gmail_message_id="learning-sample",
        thread_id="learning-sample",
        received_at=now,
        from_address=sender.strip(),
        to=email,
        subject=subject.strip(),
        date=now,
        snippet=message.strip()[:500],
        body=message.strip(),
    )
    try:
        decision = await run_in_threadpool(classify_with_jev, sample)
        route = route_jev_decision(decision, config.confidence_threshold)
        return JSONResponse(
            {
                "model": decision.model,
                "judgments": {
                    "category": {
                        "selected": decision.category,
                        "confidence": decision.confidence,
                        "probabilities": decision.probabilities,
                    },
                    "requires_action": {"yes_probability": decision.action_probability},
                    "urgency": {"score": decision.urgency_score, "minimum": 0, "maximum": 2},
                },
                "policy": {
                    "route": route.name,
                    "category_to_apply": route.category_to_apply,
                    "threshold": config.confidence_threshold,
                    "reason": route.reason,
                },
            }
        )
    except Exception as error:
        return _json_error(str(error) or "Learning sample failed", 500)


@app.post("/api/cron/classify")
def cron_classify(request: Request) -> JSONResponse:
    authorization = request.headers.get("authorization", "")
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(provided, config.cron_secret):
        return _json_error("Unauthorized", 401)
    try:
        return JSONResponse(run_classification_job(config.allowed_email, "cron"))
    except JobAlreadyRunningError as error:
        return _json_error(str(error), 409)
    except Exception as error:
        return _json_error(str(error) or "Classification failed", 500)


@app.patch("/api/classifications/{classification_id}")
async def update_classification(classification_id: int, request: Request) -> JSONResponse:
    try:
        assert_same_origin(request)
    except PermissionError as error:
        return _json_error(str(error), 403)
    email = get_session_email(request)
    if not email:
        return _json_error("Not authenticated", 401)
    try:
        body = await _read_json_object(request)
    except ValueError as error:
        return _json_error(str(error), 400)
    category = body.get("category")
    if classification_id < 1 or not is_category_key(category):
        return _json_error("Invalid classification update", 400)
    try:
        await run_in_threadpool(apply_reviewed_category, email, classification_id, category)
        return JSONResponse({"ok": True})
    except Exception as error:
        return _json_error(str(error) or "Update failed", 500)


@app.post("/api/auth/disconnect")
def disconnect(request: Request) -> JSONResponse:
    try:
        assert_same_origin(request)
    except PermissionError as error:
        return _json_error(str(error), 403)
    email = get_session_email(request)
    if not email:
        return _json_error("Not authenticated", 401)
    try:
        with suppress(Exception):
            revoke_google_token(email)
        delete_user(email)
        response = JSONResponse({"ok": True})
        clear_session(response)
        return response
    except Exception:
        return _json_error("Could not disconnect Gmail", 500)


@app.post("/api/auth/logout")
def logout(request: Request) -> JSONResponse:
    try:
        assert_same_origin(request)
    except PermissionError:
        return _json_error("Invalid request", 403)
    response = JSONResponse({"ok": True})
    clear_session(response)
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, error: HTTPException) -> JSONResponse:
    return _json_error(str(error.detail), error.status_code)
