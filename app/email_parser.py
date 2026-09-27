"""Extraction of bounded plain-text email content from Gmail messages."""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class EmailContent:
    gmail_message_id: str
    thread_id: str
    received_at: str
    from_address: str
    to: str
    subject: str
    date: str
    snippet: str
    body: str


def _decode_base64url(data: str | None) -> str:
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        return raw.decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _strip_html(value: str) -> str:
    value = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<br\s*/?\s*>", "\n", value, flags=re.I)
    value = re.sub(r"</p\s*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(
        r"&#(\d+);",
        lambda match: (
            chr(int(match.group(1)))
            if 0 <= int(match.group(1)) <= 0x10FFFF
            else f"&amp;#{match.group(1)};"
        ),
        value,
    )
    value = html.unescape(value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return re.sub(r"[ \t]{2,}", " ", value).strip()


def _is_attachment(part: dict[str, Any]) -> bool:
    """Identify MIME attachment parts before their contents enter model state."""
    if str(part.get("filename", "")).strip():
        return True
    for header in part.get("headers", []) or []:
        if str(header.get("name", "")).lower() != "content-disposition":
            continue
        disposition = str(header.get("value", "")).split(";", 1)[0].strip().lower()
        if disposition == "attachment":
            return True
    return False


def _collect_bodies(part: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    rich: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        if _is_attachment(node):
            return
        mime_type = str(node.get("mimeType", "")).lower()
        text = _decode_base64url(node.get("body", {}).get("data"))
        if text and mime_type == "text/plain":
            plain.append(text)
        elif text and mime_type == "text/html":
            rich.append(text)
        for child in node.get("parts", []) or []:
            walk(child)

    if part:
        walk(part)
    return plain, rich


def _header(headers: list[dict[str, Any]], name: str) -> str:
    for item in headers:
        if str(item.get("name", "")).lower() == name.lower():
            return str(item.get("value", "")).strip()
    return ""


def parse_gmail_message(message: dict[str, Any]) -> EmailContent:
    message_id = message.get("id")
    if not message_id:
        raise ValueError("Gmail message is missing its id")
    plain, rich = _collect_bodies(message.get("payload"))
    body = "\n\n".join(plain).strip()
    if not body:
        body = _strip_html("\n\n".join(rich))
    if not body:
        body = str(message.get("snippet", ""))
    headers = message.get("payload", {}).get("headers", []) or []
    try:
        received = datetime.fromtimestamp(int(message.get("internalDate", 0)) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        received = datetime.now(UTC)
    return EmailContent(
        gmail_message_id=str(message_id),
        thread_id=str(message.get("threadId") or message_id),
        received_at=received.isoformat().replace("+00:00", "Z"),
        from_address=_header(headers, "From"),
        to=_header(headers, "To"),
        subject=_header(headers, "Subject") or "(No subject)",
        date=_header(headers, "Date"),
        snippet=str(message.get("snippet", ""))[:500],
        body=body[:12_000],
    )
