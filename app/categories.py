"""Inbox categories and their Gmail label names."""

from __future__ import annotations

from typing import Final, TypeGuard

CATEGORIES: Final[dict[str, dict[str, str]]] = {
    "action_required": {
        "name": "Action Required",
        "description": (
            "The recipient is directly asked or clearly expected to reply, decide, "
            "submit, pay, review, or complete a task. Explicit deadlines and blocking "
            "requests belong here."
        ),
    },
    "important": {
        "name": "Important",
        "description": (
            "High consequence personal or work information the recipient should notice, "
            "with no direct action request and no better topic category below."
        ),
    },
    "finance": {
        "name": "Finance",
        "description": (
            "Banking, investments, taxes, invoices, payment status, account balances, "
            "payroll, insurance, or other financial account information. Excludes "
            "ordinary purchase receipts."
        ),
    },
    "meetings": {
        "name": "Meetings",
        "description": (
            "Calendar invitations, appointment confirmations, scheduling, rescheduling, "
            "agendas, or follow-ups whose main purpose is a meeting or event."
        ),
    },
    "newsletters": {
        "name": "Newsletters",
        "description": (
            "Recurring editorial updates, digests, publications, community roundups, "
            "or educational subscriptions primarily meant to be read."
        ),
    },
    "receipts": {
        "name": "Receipts",
        "description": (
            "Purchase receipts, order confirmations, shipping or delivery updates, "
            "booking confirmations, and transaction records for a specific purchase."
        ),
    },
    "social": {
        "name": "Social",
        "description": (
            "Social network activity, personal connection updates, comments, follows, "
            "likes, or non-urgent community notifications."
        ),
    },
    "promotions": {
        "name": "Promotions",
        "description": (
            "Marketing, sales, coupons, product announcements, offers, campaigns, or "
            "commercial messages primarily intended to drive a purchase."
        ),
    },
    "other": {
        "name": "Other",
        "description": (
            "The message does not fit any category above or does not contain enough "
            "information to decide."
        ),
    },
}

CATEGORY_KEYS: Final[tuple[str, ...]] = tuple(CATEGORIES)
LABEL_ROOT: Final = "Jev"
PROCESSED_LABEL: Final = f"{LABEL_ROOT}/Processed"
REVIEW_LABEL: Final = f"{LABEL_ROOT}/Needs Review"


def is_category_key(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and value in CATEGORIES


def category_label(category: str) -> str:
    if not is_category_key(category):
        raise ValueError(f"Unknown category: {category}")
    return f"{LABEL_ROOT}/{CATEGORIES[category]['name']}"
