import pytest

from app.jev import JevClassification
from app.routing import route_jev_decision


def _decision(confidence: float) -> JevClassification:
    return JevClassification(
        category="finance",
        confidence=confidence,
        probabilities={"finance": confidence},
        action_probability=0.2,
        urgency_score=0.5,
        model="jev-latest",
    )


def test_confident_decision_is_auto_labeled() -> None:
    route = route_jev_decision(_decision(0.8), 0.65)

    assert route.name == "auto_label"
    assert route.category_to_apply == "finance"


def test_uncertain_decision_goes_to_review() -> None:
    route = route_jev_decision(_decision(0.64), 0.65)

    assert route.name == "human_review"
    assert route.category_to_apply is None


def test_invalid_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        route_jev_decision(_decision(0.8), 1.1)
