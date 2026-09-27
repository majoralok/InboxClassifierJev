import base64

import pytest

from app.config import Config, check_runtime_config


def test_config_accepts_valid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    values = {
        "APP_URL": "https://inbox.example.com/",
        "ALLOWED_GOOGLE_EMAIL": "User@Example.com",
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "client-secret",
        "TYPESAFE_API_KEY": "typesafe-key",
        "APP_ENCRYPTION_KEY": key,
        "SESSION_SECRET": "s" * 32,
        "CRON_SECRET": "c" * 32,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = Config()

    assert config.app_url == "https://inbox.example.com"
    assert config.allowed_email == "user@example.com"
    assert config.encryption_key == b"k" * 32
    assert check_runtime_config() == []


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("APP_URL", "https://example.com/path", "HTTP\\(S\\) origin"),
        ("ALLOWED_GOOGLE_EMAIL", "not-an-email", "valid email"),
        ("SESSION_SECRET", "too-short", "at least 32"),
    ],
)
def test_config_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    monkeypatch.setenv(name, value)
    config = Config()

    with pytest.raises(ValueError, match=message):
        if name == "APP_URL":
            _ = config.app_url
        elif name == "ALLOWED_GOOGLE_EMAIL":
            _ = config.allowed_email
        else:
            _ = config.session_secret
