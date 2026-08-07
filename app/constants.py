from __future__ import annotations

from typing import Final


CATEGORIES: Final[tuple[str, ...]] = (
    "recovery",
    "accumulation",
    "execution",
    "maintenance",
)

CATEGORY_LABELS: Final[dict[str, str]] = {
    "recovery": "Recovery",
    "accumulation": "Accumulation",
    "execution": "Execution",
    "maintenance": "Maintenance",
}

DEFAULT_SETTINGS: Final[dict[str, object]] = {
    "profile_name": "Operator",
    "timezone": "UTC",
    "week_starts_on": 1,
    "time_format": "24h",
    "date_format": "DD.MM.YYYY",
    "reminder_minutes": 180,
    "daily_summary_enabled": False,
    "daily_summary_time": "21:00",
    "theme_dark": "#000000",
    "theme_light": "#ffffff",
    "theme_accent": "#00a8ff",
    "sidebar_auto_hide": True,
}


def normalize_category(value: str) -> str:
    category = str(value).strip().lower()
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {value}")
    return category

