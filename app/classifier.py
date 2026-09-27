"""Classification jobs and the human-review approval path."""

from __future__ import annotations

from app.config import config
from app.database import (
    acquire_job_lock,
    approve_classification,
    finish_job,
    get_classification,
    probabilities_json,
    release_job_lock,
    save_classification,
    start_job,
)
from app.email_parser import EmailContent
from app.gmail import (
    apply_classification_labels,
    ensure_app_labels,
    get_email,
    list_unprocessed_messages,
)
from app.jev import classify_with_jev
from app.routing import route_jev_decision

LOCK_NAME = "gmail-classification"


class JobAlreadyRunningError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("A classification job is already running")


def _error_message(error: BaseException) -> str:
    return str(error)[:1000]


def _save_failure(user_email: str, content: EmailContent, error: Exception) -> None:
    save_classification(
        {
            "user_email": user_email,
            "gmail_message_id": content.gmail_message_id,
            "thread_id": content.thread_id,
            "received_at": content.received_at,
            "from_address": content.from_address,
            "subject": content.subject,
            "snippet": content.snippet,
            "suggested_category": None,
            "applied_category": None,
            "confidence": None,
            "probabilities_json": None,
            "action_probability": None,
            "urgency_score": None,
            "model": None,
            "status": "error",
            "error": _error_message(error),
        }
    )


def run_classification_job(user_email: str, trigger: str) -> dict[str, int]:
    if not acquire_job_lock(LOCK_NAME):
        raise JobAlreadyRunningError
    result = {"processed": 0, "labeled": 0, "review": 0, "failed": 0}
    job_id = start_job(trigger)
    try:
        labels = ensure_app_labels(user_email)
        message_ids = list_unprocessed_messages(user_email, config.lookback_days, config.batch_size)
        for message_id in message_ids:
            content: EmailContent | None = None
            try:
                content = get_email(user_email, message_id)
                decision = classify_with_jev(content)
                route = route_jev_decision(decision, config.confidence_threshold)
                category = route.category_to_apply
                save_classification(
                    {
                        "user_email": user_email,
                        "gmail_message_id": content.gmail_message_id,
                        "thread_id": content.thread_id,
                        "received_at": content.received_at,
                        "from_address": content.from_address,
                        "subject": content.subject,
                        "snippet": content.snippet,
                        "suggested_category": decision.category,
                        "applied_category": category,
                        "confidence": decision.confidence,
                        "probabilities_json": probabilities_json(decision.probabilities),
                        "action_probability": decision.action_probability,
                        "urgency_score": decision.urgency_score,
                        "model": decision.model,
                        "status": "labeled" if route.name == "auto_label" else "review",
                        "error": None,
                    }
                )
                apply_classification_labels(user_email, message_id, labels, category)
                result["processed"] += 1
                result["labeled" if route.name == "auto_label" else "review"] += 1
            except Exception as error:
                result["failed"] += 1
                if content is not None:
                    _save_failure(user_email, content, error)
        finish_job(job_id, result)
        return result
    except Exception as error:
        finish_job(job_id, result, _error_message(error))
        raise
    finally:
        release_job_lock(LOCK_NAME)


def apply_reviewed_category(user_email: str, classification_id: int, category: str) -> None:
    record = get_classification(classification_id, user_email)
    if not record:
        raise ValueError("Classification not found")
    labels = ensure_app_labels(user_email)
    apply_classification_labels(user_email, record["gmail_message_id"], labels, category)
    approve_classification(classification_id, user_email, category)
