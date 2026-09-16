from __future__ import annotations

import pytest

from app.validation import validate_settings


def test_legacy_dashboard_order_is_normalized() -> None:
    order = ["cpu", "ram", "disk", "uptime", "current", "today", "recent"]

    result = validate_settings({"dashboard_order": order})

    assert result["dashboard_order"] == ["cpu", "ram", "disk", "uptime", "current", "today"]


def test_invalid_dashboard_order_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid dashboard_order"):
        validate_settings({"dashboard_order": ["cpu", "ram", "disk", "uptime", "current", "other"]})
