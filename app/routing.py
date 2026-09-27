"""Deterministic policy that turns Jev judgments into application actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.jev import JevClassification

RouteName = Literal["auto_label", "human_review"]


@dataclass(frozen=True)
class InboxRoute:
    """An auditable action selected by ordinary Python code."""

    name: RouteName
    category_to_apply: str | None
    reason: str


def route_jev_decision(
    decision: JevClassification,
    confidence_threshold: float,
) -> InboxRoute:
    """Route a typed Jev result without asking a second model to make policy."""
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")

    if decision.confidence < confidence_threshold:
        return InboxRoute(
            name="human_review",
            category_to_apply=None,
            reason=(
                f"Category confidence {decision.confidence:.0%} is below the "
                f"{confidence_threshold:.0%} auto-label threshold."
            ),
        )

    return InboxRoute(
        name="auto_label",
        category_to_apply=decision.category,
        reason=(
            f"Category confidence {decision.confidence:.0%} meets the "
            f"{confidence_threshold:.0%} auto-label threshold."
        ),
    )
