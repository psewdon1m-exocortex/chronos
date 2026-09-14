from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .constants import CATEGORIES, DEFAULT_SETTINGS


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile_name: str | None = Field(default=None, min_length=1, max_length=64)
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    week_starts_on: int | None = Field(default=None, ge=1, le=7)
    time_format: str | None = None
    date_format: str | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080)
    daily_summary_enabled: bool | None = None
    daily_summary_time: str | None = None
    theme_accent: str | None = None
    sidebar_auto_hide: bool | None = None
    navigation_order: list[str] | None = None
    dashboard_order: list[str] | None = None
    settings_order: list[str] | None = None


def validate_settings(data: dict[str, Any] | SettingsInput) -> dict[str, Any]:
    try:
        model = data if isinstance(data, SettingsInput) else SettingsInput.model_validate(data)
    except ValidationError as error:
        raise ValueError("Invalid settings fields or types") from error
    values = model.model_dump(exclude_none=True)
    if "timezone" in values:
        try:
            ZoneInfo(values["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Unknown timezone") from error
    for key, allowed in {"time_format": {"12h", "24h"}, "date_format": {"DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"}}.items():
        if key in values and values[key] not in allowed:
            raise ValueError(f"Unsupported {key}")
    for key, pattern in {"daily_summary_time": r"(?:[01]\d|2[0-3]):[0-5]\d", "theme_accent": r"#[0-9a-fA-F]{6}"}.items():
        if key in values and not re.fullmatch(pattern, values[key]):
            raise ValueError(f"Invalid {key}")
    for key in ("navigation_order", "dashboard_order", "settings_order"):
        if key in values and (len(values[key]) != len(DEFAULT_SETTINGS[key]) or set(values[key]) != set(DEFAULT_SETTINGS[key])):
            raise ValueError(f"Invalid {key}")
    return values


def validate_session(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Invalid backup session")
    value = dict(item)
    identifier = value.get("id")
    public = value.get("public_id")
    if type(identifier) is not int or not 0 < identifier < 2**63 - 1:
        raise ValueError("Invalid backup session ID")
    if not isinstance(public, str) or not re.fullmatch(r"t-[0-9]{8,18}", public) or not 0 < int(public[2:]) < 2**63 - 1:
        raise ValueError("Invalid backup public ID")
    if value.get("category") not in CATEGORIES or value.get("source", "restore") not in {"telegram", "web", "manual", "restore"}:
        raise ValueError("Invalid backup session category or source")
    for key in ("started_at", "stopped_at", "deleted_at"):
        raw = value.get(key)
        try:
            stamp = datetime.fromisoformat(raw) if raw is not None else None
        except (ValueError, TypeError) as error:
            raise ValueError("Invalid backup timestamp") from error
        if (key == "started_at" and stamp is None) or (stamp is not None and stamp.tzinfo is None):
            raise ValueError("Backup timestamps must include a timezone")
        value[key] = stamp
    if value["stopped_at"] is not None and value["stopped_at"] < value["started_at"]:
        raise ValueError("Session stop precedes start")
    for key in ("duration_seconds", "carried_seconds"):
        number = value.get(key, 0 if key == "carried_seconds" else None)
        if number is not None and (type(number) is not int or not 0 <= number <= 2**31 - 1):
            raise ValueError("Invalid backup duration")
    note = value.get("note", "")
    group = value.get("timer_group_key")
    if not isinstance(note, str) or len(note) > 500 or (group is not None and (not isinstance(group, str) or len(group) > 128)):
        raise ValueError("Invalid backup session metadata")
    return value
