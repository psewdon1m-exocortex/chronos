from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.timer_service import TimerError, TimerService


pytestmark = pytest.mark.asyncio


async def test_start_switch_stop_and_undo_are_consistent(store) -> None:
    service = TimerService(store)
    base = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

    started = await service.press("recovery", actor="test", source="web", now=base)
    assert started["started"]["category"] == "recovery"

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

