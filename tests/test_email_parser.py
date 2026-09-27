import base64

from app.email_parser import parse_gmail_message


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_parse_prefers_plain_text_and_skips_attachments() -> None:
    message = {
        "id": "message-1",
        "threadId": "thread-1",
        "internalDate": "1704067200000",
        "snippet": "A short preview",
        "payload": {
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "you@example.com"},
                {"name": "Subject", "value": "Please review"},
            ],
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _encoded("Visible body")}},
                {
                    "mimeType": "text/plain",
                    "filename": "private.txt",
                    "body": {"data": _encoded("Attachment contents")},
                },
            ],
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed.gmail_message_id == "message-1"
    assert parsed.thread_id == "thread-1"
    assert parsed.subject == "Please review"
    assert parsed.body == "Visible body"
    assert "Attachment" not in parsed.body


def test_parse_sanitizes_html_when_plain_text_is_absent() -> None:
    message = {
        "id": "message-2",
        "snippet": "fallback",
        "payload": {
            "headers": [],
            "mimeType": "text/html",
            "body": {
                "data": _encoded(
                    "<style>hidden</style><p>Hello &amp; welcome</p><script>bad()</script>"
                )
            },
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed.subject == "(No subject)"
    assert parsed.body == "Hello & welcome"
