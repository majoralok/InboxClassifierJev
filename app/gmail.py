"""Bounded Gmail API access for reading messages and applying labels."""

from __future__ import annotations

from urllib.parse import urlencode
from urllib.request import Request, urlopen

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build  # type: ignore[import-untyped]

from app.categories import (
    CATEGORY_KEYS,
    PROCESSED_LABEL,
    REVIEW_LABEL,
    category_label,
)
from app.email_parser import EmailContent, parse_gmail_message
from app.google_auth import get_authorized_credentials


def _service(email: str) -> tuple[Resource, Credentials]:
    credentials = get_authorized_credentials(email)
    return (
        build("gmail", "v1", credentials=credentials, cache_discovery=False),
        credentials,
    )


def list_unprocessed_messages(email: str, lookback_days: int, max_results: int) -> list[str]:
    service, _ = _service(email)
    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            labelIds=["INBOX"],
            q=f"newer_than:{lookback_days}d -label:{PROCESSED_LABEL}",
            maxResults=max_results,
            includeSpamTrash=False,
        )
        .execute()
    )
    return [str(item["id"]) for item in response.get("messages", []) if item.get("id")]


def get_email(email: str, message_id: str) -> EmailContent:
    service, _ = _service(email)
    response = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    return parse_gmail_message(response)


def ensure_app_labels(email: str) -> dict[str, str]:
    service, _ = _service(email)
    response = service.users().labels().list(userId="me").execute()
    labels = {
        str(item["name"]): str(item["id"])
        for item in response.get("labels", [])
        if item.get("name") and item.get("id")
    }
    required = [
        PROCESSED_LABEL,
        REVIEW_LABEL,
        *(category_label(category) for category in CATEGORY_KEYS),
    ]
    for name in required:
        if name in labels:
            continue
        created = (
            service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        if not created.get("id"):
            raise ValueError(f"Gmail did not return an id for label {name}")
        labels[name] = str(created["id"])
    return labels


def apply_classification_labels(
    email: str,
    message_id: str,
    labels: dict[str, str],
    category: str | None,
) -> None:
    category_ids = [
        labels[category_label(key)] for key in CATEGORY_KEYS if category_label(key) in labels
    ]
    review_id = labels.get(REVIEW_LABEL)
    processed_id = labels.get(PROCESSED_LABEL)
    if not review_id or not processed_id:
        raise ValueError("Required Gmail labels are unavailable")
    selected = labels.get(category_label(category)) if category else review_id
    if not selected:
        raise ValueError("Selected Gmail label is unavailable")
    add_label_ids = [processed_id, selected]
    added = set(add_label_ids)
    service, _ = _service(email)
    (
        service.users()
        .messages()
        .modify(
            userId="me",
            id=message_id,
            body={
                "addLabelIds": add_label_ids,
                "removeLabelIds": [
                    item for item in [*category_ids, review_id] if item not in added
                ],
            },
        )
        .execute()
    )


def revoke_google_token(email: str) -> None:
    credentials = get_authorized_credentials(email)
    token = credentials.refresh_token or credentials.token
    if not token:
        return
    body = urlencode({"token": token}).encode()
    request = Request(
        "https://oauth2.googleapis.com/revoke",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=10):  # noqa: S310 - fixed Google HTTPS endpoint
        return
