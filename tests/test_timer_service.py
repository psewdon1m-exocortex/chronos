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


async def test_backfill_without_active_timer_creates_only_a_completed_session(store) -> None:
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

    result = await service.backfill_completed(
        "recovery",
        90,
        actor="test",
        source="telegram",
        now=base + timedelta(hours=2),
    )

    assert result["created"]["started_at"] == (base + timedelta(minutes=30)).isoformat()
    assert result["created"]["stopped_at"] == (base + timedelta(hours=2)).isoformat()
    assert result["created"]["active"] is False
    assert result["active"] is None
    assert await service.active(now=base + timedelta(hours=2)) is None
    assert result["trimmed_ids"] == [first["public_id"]]
    assert result["deleted_ids"] == [second["public_id"]]
    history = await service.history(
        start=None, end=None, category=None, query="", limit=10, offset=0
    )
    assert result["created"]["duration_seconds"] == 5400
    assert [item["public_id"] for item in history["items"]] == [
        result["created"]["public_id"],
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


async def test_backfill_deducts_partial_overlap_and_continues_active_timer(store) -> None:
    service = TimerService(store)
    base = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)
    started = await service.press(
        "execution", actor="test", source="telegram", now=base
    )
    current = base + timedelta(hours=2)

    result = await service.backfill_completed(
        "recovery",
        50,
        actor="test",
        source="telegram",
        now=current,
    )

    assert result["created"]["active"] is False
    assert result["created"]["duration_seconds"] == 3000
    assert result["active"]["category"] == "execution"
    assert result["active"]["duration_seconds"] == 0
    assert result["active"]["timer_elapsed_seconds"] == 4200
    active_later = await service.active(now=current + timedelta(minutes=10))
    assert active_later and active_later["timer_elapsed_seconds"] == 4800

    analytics = await service.analytics(
        base,
        current + timedelta(minutes=10),
        now=current + timedelta(minutes=10),
    )
    totals = {item["category"]: item["seconds"] for item in analytics["categories"]}
    assert totals["execution"] == 4800
    assert totals["recovery"] == 3000

    await service.undo(actor="test")
    restored = await service.active(now=current)
    assert restored
    assert restored["public_id"] == started["started"]["public_id"]
    assert restored["timer_elapsed_seconds"] == 7200


async def test_backfill_resets_fully_overlapped_active_timer_to_zero(store) -> None:
    service = TimerService(store)
    current = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
    started = await service.press(
        "maintenance",
        actor="test",
        source="telegram",
        now=current - timedelta(minutes=15),
    )

    result = await service.backfill_completed(
        "accumulation",
        30,
        actor="test",
        source="telegram",
        now=current,
    )

    assert result["created"]["duration_seconds"] == 1800
    assert result["active"]["category"] == "maintenance"
    assert result["active"]["timer_elapsed_seconds"] == 0
    assert result["deleted_ids"] == [started["started"]["public_id"]]


async def test_backfill_preserves_both_sides_of_a_spanning_completed_session(store) -> None:
    service = TimerService(store)
    base = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)
    original = await service.create_manual(
        category="execution",
        started_at=base,
        stopped_at=base + timedelta(hours=3),
        note="Spanning session",
        actor="test",
    )

    result = await service.backfill_completed(
        "recovery",
        60,
        actor="test",
        source="telegram",
        now=base + timedelta(hours=2),
    )

    assert result["active"] is None
    history = await service.history(
        start=None, end=None, category=None, query="", limit=10, offset=0
    )
    assert [item["duration_seconds"] for item in history["items"]] == [3600, 3600, 3600]
    assert [item["category"] for item in history["items"]] == [
        "execution",
        "recovery",
        "execution",
    ]

    await service.undo(actor="test")
    restored = await service.history(
        start=None, end=None, category=None, query="", limit=10, offset=0
    )
    assert len(restored["items"]) == 1
    assert restored["items"][0]["public_id"] == original["public_id"]
    assert restored["items"][0]["duration_seconds"] == 10800


async def test_repeated_backfill_deducts_earlier_segments_of_the_active_timer(store) -> None:
    service = TimerService(store)
    base = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)
    await service.press("execution", actor="test", source="telegram", now=base)
    await service.backfill_completed(
        "recovery",
        50,
        actor="test",
        source="telegram",
        now=base + timedelta(hours=2),
    )

    result = await service.backfill_completed(
        "accumulation",
        90,
        actor="test",
        source="telegram",
        now=base + timedelta(hours=2, minutes=30),
    )

    assert result["active"]["category"] == "execution"
    assert result["active"]["timer_elapsed_seconds"] == 3600
    analytics = await service.analytics(
        base,
        base + timedelta(hours=2, minutes=30),
        now=base + timedelta(hours=2, minutes=30),
    )
    totals = {item["category"]: item["seconds"] for item in analytics["categories"]}
    assert totals["execution"] == 3600
    assert totals["recovery"] == 0
    assert totals["accumulation"] == 5400


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
