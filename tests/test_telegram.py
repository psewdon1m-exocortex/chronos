from __future__ import annotations

from app.constants import CATEGORIES, CATEGORY_LABELS
from app.telegram import category_choice_keyboard, format_duration


def test_category_choice_keyboard_contains_all_categories() -> None:
    keyboard = category_choice_keyboard("retype:t-00000001")
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert [button.text for button in buttons] == [
        CATEGORY_LABELS[category] for category in CATEGORIES
    ]
    assert [button.callback_data for button in buttons] == [
        f"chronos:retype:t-00000001:{category}" for category in CATEGORIES
    ]


def test_format_duration_includes_all_nonzero_units() -> None:
    assert format_duration(90061) == "1d 1h 1m 1s"
