"""Environment-backed application configuration."""

from __future__ import annotations

import base64
import binascii
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
REQUIRED_NAMES = (
    "APP_URL",
    "ALLOWED_GOOGLE_EMAIL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "TYPESAFE_API_KEY",
    "APP_ENCRYPTION_KEY",
    "SESSION_SECRET",
    "CRON_SECRET",
)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _secret(name: str) -> str:
    value = _required(name)
    if len(value) < 32:
        raise ValueError(f"{name} must be at least 32 characters")
    return value


def _number(name: str, fallback: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be between {minimum} and {maximum}") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _integer(name: str, fallback: int, minimum: int, maximum: int) -> int:
    value = _number(name, fallback, minimum, maximum)
    if int(value) != value:
        raise ValueError(f"{name} must be an integer")
    return int(value)


class Config:
    @property
    def app_url(self) -> str:
        raw = _required("APP_URL")
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "APP_URL must be an HTTP(S) origin without credentials, a path, "
                "a query, or a fragment"
            )
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def allowed_email(self) -> str:
        value = _required("ALLOWED_GOOGLE_EMAIL").lower()
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("ALLOWED_GOOGLE_EMAIL must be a valid email address")
        return value

    @property
    def google_client_id(self) -> str:
        return _required("GOOGLE_CLIENT_ID")

    @property
    def google_client_secret(self) -> str:
        return _required("GOOGLE_CLIENT_SECRET")

    @property
    def typesafe_api_key(self) -> str:
        return _required("TYPESAFE_API_KEY")

    @property
    def encryption_key(self) -> bytes:
        value = _required("APP_ENCRYPTION_KEY")
        try:
            encoded = value.encode("ascii")
            key = base64.b64decode(
                encoded + b"=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, UnicodeEncodeError, ValueError, TypeError) as error:
            raise ValueError(
                "APP_ENCRYPTION_KEY must be a base64url-encoded 32-byte key"
            ) from error
        if len(key) != 32:
            raise ValueError("APP_ENCRYPTION_KEY must be a base64url-encoded 32-byte key")
        return key

    @property
    def session_secret(self) -> str:
        return _secret("SESSION_SECRET")

    @property
    def cron_secret(self) -> str:
        return _secret("CRON_SECRET")

    @property
    def database_path(self) -> str:
        value = os.getenv("DATABASE_PATH", "./data/inbox-classifier.db")
        return value if value == ":memory:" else str(Path(value).resolve())

    @property
    def confidence_threshold(self) -> float:
        return _number("CLASSIFICATION_CONFIDENCE_THRESHOLD", 0.65, 0, 1)

    @property
    def batch_size(self) -> int:
        return _integer("DEFAULT_BATCH_SIZE", 25, 1, 100)

    @property
    def lookback_days(self) -> int:
        return _integer("EMAIL_LOOKBACK_DAYS", 30, 1, 3650)

    @property
    def production(self) -> bool:
        return os.getenv("ENVIRONMENT", "development").lower() == "production"


config = Config()


def check_runtime_config() -> list[str]:
    errors = [name for name in REQUIRED_NAMES if not os.getenv(name, "").strip()]
    if errors:
        return errors
    checks = (
        ("APP_URL", lambda: config.app_url),
        ("ALLOWED_GOOGLE_EMAIL", lambda: config.allowed_email),
        ("APP_ENCRYPTION_KEY", lambda: config.encryption_key),
        ("SESSION_SECRET", lambda: config.session_secret),
        ("CRON_SECRET", lambda: config.cron_secret),
        ("CLASSIFICATION_CONFIDENCE_THRESHOLD", lambda: config.confidence_threshold),
        ("DEFAULT_BATCH_SIZE", lambda: config.batch_size),
        ("EMAIL_LOOKBACK_DAYS", lambda: config.lookback_days),
    )
    for name, check in checks:
        try:
            check()
        except ValueError as error:
            errors.append(f"{name} ({error})")
    return errors
