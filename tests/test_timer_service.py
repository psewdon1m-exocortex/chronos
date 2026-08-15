from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

import pytest

from app.timer_service import TimerError, TimerService


pytestmark = pytest.mark.asyncio


async def test_start_switch_stop_and_undo_are_consistent(store) -> None:
    service = TimerService(store)
    base = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

    started = await service.press("recovery", actor="test", source="web", now=base)
    assert started["started"]["category"] == "recovery"
    assert re.fullmatch(r"t-\d{8,}", started["started"]["public_id"])

    switched = await service.press(
        "execution", actor="test", source="web", now=base + timedelta(hours=1)
    )
    assert switched["stopped"]["duration_seconds"] == 3600
    assert switched["started"]["category"] == "execution"

    stopped = await service.stop(actor="test", now=base + timedelta(hours=3))
    assert stopped and stopped["duration_seconds"] == 7200
    assert await service.active() is None

    undone = await service.undo(actor="test")
    assert undone["undone"] == "timer.stopped"
    active = await service.active(now=base + timedelta(hours=3))
    assert active and active["category"] == "execution"


async def test_manual_sessions_reject_overlap(store) -> None:
    service = TimerService(store)
    start = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
    await service.create_manual(
        category="maintenance",
        started_at=start,
        stopped_at=start + timedelta(hours=1),
        note="Administration",
        actor="test",
    )
    with pytest.raises(TimerError, match="overlaps"):
        await service.create_manual(
            category="execution",
            started_at=start + timedelta(minutes=30),
            stopped_at=start + timedelta(hours=2),
            note="Conflict",
            actor="test",
        )


async def test_session_update_excludes_the_edited_session(store) -> None:
    service = TimerService(store)
    start = datetime(2026, 8, 5, 10, 0, 37, tzinfo=timezone.utc)
    session = await service.create_manual(
        category="maintenance",
        started_at=start,
        stopped_at=start + timedelta(hours=1),
        note="Administration",
        actor="test",
    )
    updated = await service.update_session(
        session["id"],
        category="execution",
        started_at=start + timedelta(minutes=5),
        stopped_at=start + timedelta(minutes=55),
        note="Focused work",
        actor="test",
    )
    assert updated["id"] == session["id"]
    assert updated["public_id"] == session["public_id"]
    assert updated["category"] == "execution"
    assert updated["duration_seconds"] == 3000


async def test_retype_changes_only_the_last_completed_session(store) -> None:
    service = TimerService(store)
    base = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)
    first = await service.create_manual(
        category="maintenance",
        started_at=base,
        stopped_at=base + timedelta(hours=1),
        note="First",
        actor="test",
    )
    second = await service.create_manual(
        category="recovery",
        started_at=base + timedelta(hours=1),
        stopped_at=base + timedelta(hours=2),
        note="Second",
        actor="test",
    )

    with pytest.raises(TimerError, match="changed"):
        await service.retype_last_completed(
            "accumulation",
            actor="test",
            expected_public_id=first["public_id"],
        )

    changed = await service.retype_last_completed(
        "accumulation",
        actor="test",
        expected_public_id=second["public_id"],
    )

    assert changed["id"] == second["id"]
    assert changed["category"] == "accumulation"
    history = await service.history(
        start=None, end=None, category=None, query="", limit=10, offset=0
    )
    categories = {item["id"]: item["category"] for item in history["items"]}
    assert categories[first["id"]] == "maintenance"
    assert categories[second["id"]] == "accumulation"


async def test_backfill_trims_and_removes_overlapped_sessions_and_can_be_undone(store) -> None:
    service = TimerService(store)
    base = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)
    first = await service.create_manual(
        category="maintenance",
        started_at=base,
        stopped_at=base + timedelta(hours=1),
        note="First",
        actor="test",
    )
    second = await service.create_manual(
        category="execution",
        started_at=base + timedelta(hours=1),
        stopped_at=base + timedelta(hours=2),
        note="Second",
        actor="test",
    )

    result = await service.backfill_active(
        "recovery",
        90,
        actor="test",
        source="telegram",
        now=base + timedelta(hours=2),
    )

    assert result["started"]["started_at"] == (base + timedelta(minutes=30)).isoformat()
    assert result["started"]["active"] is True
    assert result["trimmed_ids"] == [first["public_id"]]
    assert result["deleted_ids"] == [second["public_id"]]
    history = await service.history(
        start=None, end=None, category=None, query="", limit=10, offset=0
    )
    assert result["started"]["duration_seconds"] == 5400
    assert [item["public_id"] for item in history["items"]] == [
        result["started"]["public_id"],
        first["public_id"],
    ]
    assert history["items"][1]["duration_seconds"] == 1800

    await service.undo(actor="test")
    restored = await service.history(
        start=None, end=None, category=None, query="", limit=10, offset=0
    )
    assert {item["public_id"] for item in restored["items"]} == {
        first["public_id"],
        second["public_id"],
    }


async def test_analytics_clips_sessions_to_period_boundaries(store) -> None:
    service = TimerService(store)
    session_start = datetime(2026, 8, 4, 23, 30, tzinfo=timezone.utc)
    await service.create_manual(
        category="recovery",
        started_at=session_start,
        stopped_at=session_start + timedelta(hours=1),
        note="Crosses midnight",
        actor="test",
    )
    result = await service.analytics(
        datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 6, 0, 0, tzinfo=timezone.utc),
    )
    recovery = next(item for item in result["categories"] if item["category"] == "recovery")
    assert recovery["seconds"] == 1800
    assert recovery["percent"] == 100.0


async def test_analytics_buckets_days_in_the_requested_timezone(store) -> None:
    service = TimerService(store)
    zone = ZoneInfo("Europe/Istanbul")
    await service.create_manual(
        category="execution",
        started_at=datetime(2026, 8, 5, 23, 30, tzinfo=zone),
        stopped_at=datetime(2026, 8, 6, 0, 30, tzinfo=zone),
        note="Local midnight",
        actor="test",
    )
    start, end = await service.period_for_dates(
        datetime(2026, 8, 5).date(),
        datetime(2026, 8, 6).date(),
        "Europe/Istanbul",
    )

    result = await service.analytics(start, end)

    assert [(day["date"], day["total_seconds"]) for day in result["days"]] == [
        ("2026-08-05", 1800),
        ("2026-08-06", 1800),
    ]
