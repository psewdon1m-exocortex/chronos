from __future__ import annotations

from datetime import datetime, timezone
import copy

import pytest

from app.security import hash_password, verify_password
from app.timer_service import TimerService


@pytest.mark.asyncio
async def test_restore_preserves_gaps_provenance_undo_and_next_identifier(store):
    timers = TimerService(store)
    def stamp(hour): return datetime(2026, 9, 10, hour, tzinfo=timezone.utc)
    first = await timers.create_manual(category="execution", started_at=stamp(1), stopped_at=stamp(2), note="first", actor="operator")
    second = await timers.create_manual(category="recovery", started_at=stamp(3), stopped_at=stamp(4), note="second", actor="operator")
    await timers.delete_session(first["id"], actor="operator")
    backup = await store.logical_backup()
    before = copy.deepcopy(backup)
    assert await store.restore_backup(backup) == 2
    assert backup == before, "Restore must not mutate its input or retained pre-restore snapshot"
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow("select source,public_id from time_sessions where id=$1", second["id"])
        assert row["source"] == "manual" and row["public_id"] == second["public_id"]
    undone = await timers.undo(actor="operator")
    assert first["id"] in undone["restored_ids"]
    third = await timers.create_manual(category="maintenance", started_at=stamp(5), stopped_at=stamp(6), note="after restore", actor="operator")
    assert third["id"] > second["id"]
    assert third["public_id"] not in {first["public_id"], second["public_id"]}


@pytest.mark.asyncio
async def test_backup_recovers_rotated_verifier_and_invalidates_sessions(store):
    await store.update_password(hash_password("new-restored-access-key"))
    backup = await store.logical_backup()
    await store.update_password(hash_password("temporary-target-access-key"))
    previous = (await store.security())["session_generation"]
    await store.restore_backup(backup)
    security = await store.security()
    assert security["session_generation"] > previous
    assert verify_password("new-restored-access-key", security["password_hash"])
    assert not verify_password("temporary-target-access-key", security["password_hash"])
    assert "new-restored-access-key" not in str(backup)


@pytest.mark.asyncio
async def test_restore_rejects_domain_errors_before_mutation(store):
    backup = await store.logical_backup()
    invalid = copy.deepcopy(backup)
    invalid["settings"]["timezone"] = "Mars/Phobos"
    with pytest.raises(ValueError, match="timezone"):
        await store.restore_backup(invalid)
    invalid = copy.deepcopy(backup)
    invalid["settings"]["daily_summary_enabled"] = "false"
    with pytest.raises(ValueError, match="settings"):
        await store.restore_backup(invalid)
    assert (await store.logical_backup())["settings"] == backup["settings"]


@pytest.mark.asyncio
async def test_logout_revocation_survives_store_recreation_and_preserves_other_sessions(store):
    from app.store import Store
    expiry = int(datetime.now(timezone.utc).timestamp()) + 3600
    await store.revoke_session("synthetic-replayed-session", expiry)
    recreated = Store(store.pool, audit_max_entries=1000, audit_retention_days=30)
    assert await recreated.session_revoked("synthetic-replayed-session")
    assert not await recreated.session_revoked("different-session")


@pytest.mark.asyncio
async def test_gryphon_deduplication_survives_restore_and_failure_rolls_back_mutation(store):
    from app.gryphon import GryphonCommandService
    from test_gryphon import envelope
    timers = TimerService(store)
    service = GryphonCommandService(store, timers)
    event = envelope("durable-command", "press", {"category": "execution"})
    result = await service.handle(event)
    backup = await store.logical_backup()
    await store.restore_backup(backup)
    assert await service.handle(event) == result
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("select count(*) from time_sessions") == 1
    original = store.complete_gryphon_event
    async def fail_after_timer(*_): raise RuntimeError("synthetic failure between mutation and dedup completion")
    store.complete_gryphon_event = fail_after_timer
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await service.handle(envelope("rollback-command", "press", {"category": "recovery"}))
    store.complete_gryphon_event = original
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("select count(*) from time_sessions") == 1
        assert await connection.fetchval("select count(*) from gryphon_events where event_id='rollback-command'") == 0


def test_disk_usage_counts_reserved_blocks_as_unavailable(monkeypatch, tmp_path):
    import types
    import app.telemetry as module
    monkeypatch.setattr(module.os, "statvfs", lambda _: types.SimpleNamespace(f_blocks=100, f_bfree=50, f_bavail=30, f_frsize=1))
    disk = module.TelemetrySampler(tmp_path).sample()["disk"]
    assert disk["used_bytes"] == 70 and disk["available_bytes"] == 30
    assert disk["percent"] == 70 and disk["scope"] == str(tmp_path)
