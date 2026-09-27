import pytest

from app.categories import category_label, is_category_key


def test_category_label_uses_human_readable_name() -> None:
    assert category_label("action_required") == "Jev/Action Required"


def test_unknown_category_is_rejected() -> None:
    assert not is_category_key("spam")
    with pytest.raises(ValueError, match="Unknown category"):
        category_label("spam")
