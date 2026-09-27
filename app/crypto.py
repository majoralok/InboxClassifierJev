"""Authenticated encryption and signed-cookie helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import config


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encrypt_json(value: Any) -> str:
    nonce = os.urandom(12)
    plaintext = json.dumps(value, separators=(",", ":")).encode()
    encrypted = AESGCM(config.encryption_key).encrypt(nonce, plaintext, None)
    ciphertext, tag = encrypted[:-16], encrypted[-16:]
    return ".".join(("v1", _b64encode(nonce), _b64encode(tag), _b64encode(ciphertext)))


def decrypt_json(encoded: str) -> Any:
    try:
        version, nonce_raw, tag_raw, ciphertext_raw = encoded.split(".")
        if version != "v1":
            raise ValueError
        encrypted = _b64decode(ciphertext_raw) + _b64decode(tag_raw)
        plaintext = AESGCM(config.encryption_key).decrypt(_b64decode(nonce_raw), encrypted, None)
        return json.loads(plaintext)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid encrypted value") from error


def sign_value(value: str) -> str:
    signature = hmac.new(config.session_secret.encode(), value.encode(), hashlib.sha256).digest()
    return f"{value}.{_b64encode(signature)}"


def verify_signed_value(signed: str) -> str | None:
    value, separator, signature = signed.rpartition(".")
    if not separator or not value:
        return None
    expected = hmac.new(config.session_secret.encode(), value.encode(), hashlib.sha256).digest()
    try:
        actual = _b64decode(signature)
    except (ValueError, TypeError):
        return None
    return value if hmac.compare_digest(actual, expected) else None


__all__ = ["decrypt_json", "encrypt_json", "sign_value", "verify_signed_value"]
