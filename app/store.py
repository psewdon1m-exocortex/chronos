from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Iterable

import asyncpg

from .constants import DEFAULT_SETTINGS
from .security import hash_password


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def serialize_session(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "public_id": str(row["public_id"]),
        "user_id": int(row["user_id"]),
        "category": str(row["category"]),
        "started_at": row["started_at"].isoformat(),
        "stopped_at": row["stopped_at"].isoformat() if row["stopped_at"] else None,
        "duration_seconds": row["duration_seconds"],
        "carried_seconds": int(row.get("carried_seconds", 0) or 0),
        "timer_group_key": row.get("timer_group_key"),
        "note": str(row.get("note", "")),
        "source": str(row.get("source", "web")),
        "deleted_at": row["deleted_at"].isoformat() if row.get("deleted_at") else None,
    }


class Store:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        audit_max_entries: int,
        audit_retention_days: int,
    ) -> None:
        self.pool = pool
        self.audit_max_entries = audit_max_entries
        self.audit_retention_days = audit_retention_days

    async def initialize(
        self,
        *,
        admin_username: str,
        admin_password: str,
        default_timezone: str,
        kernel_url_seed: str = "",
        kernel_token_ciphertext_seed: str = "",
    ) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                owner = await connection.fetchrow("select id from users order by id limit 1")
                if owner is None:
                    await connection.execute(
                        "insert into users default values"
                    )
                security = await connection.fetchval(
                    "select 1 from operator_security where id = 1"
                )
                if not security:
                    await connection.execute(
                        """
                        insert into operator_security (id, username, password_hash)
                        values (1, $1, $2)
                        """,
                        admin_username,
                        hash_password(admin_password),
                    )
                defaults = {**DEFAULT_SETTINGS, "timezone": default_timezone}
                for key, value in defaults.items():
                    await connection.execute(
                        """
                        insert into app_settings (key, value)
                        values ($1, $2::jsonb)
                        on conflict (key) do nothing
                        """,
                        key,
                        json.dumps(value),
                    )
                await connection.execute(
                    """
                    insert into service_credentials (
                        id, kernel_url, kernel_token_ciphertext
                    ) values (1, $1, $2)
                    on conflict (id) do nothing
                    """,
                    kernel_url_seed,
                    kernel_token_ciphertext_seed,
                )

    async def owner(self, connection: asyncpg.Connection | None = None) -> asyncpg.Record:
        if connection is not None:
            row = await connection.fetchrow(
                "select id, created_at from users order by id limit 1"
            )
            if row is None:
                raise RuntimeError("Chronos owner is not initialized")
            return row
        async with self.pool.acquire() as acquired:
            return await self.owner(acquired)

    async def security(self) -> asyncpg.Record:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select username, password_hash, session_generation, updated_at
                from operator_security where id = 1
                """
            )
            if row is None:
                raise RuntimeError("Chronos operator security is not initialized")
            return row

    async def update_password(self, password_hash: str) -> int:
        async with self.pool.acquire() as connection:
            generation = await connection.fetchval(
                """
                update operator_security
                set password_hash = $1,
                    session_generation = session_generation + 1,
                    updated_at = now()
                where id = 1
                returning session_generation
                """,
                password_hash,
            )
            return int(generation)

    async def kernel_credentials(self) -> asyncpg.Record:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select kernel_url, kernel_token_ciphertext, updated_at
                from service_credentials where id = 1
                """
            )
            if row is None:
                raise RuntimeError("Chronos service credentials are not initialized")
            return row

    async def update_kernel_credentials(
        self, *, kernel_url: str, kernel_token_ciphertext: str | None = None
    ) -> None:
        async with self.pool.acquire() as connection:
            if kernel_token_ciphertext is None:
                await connection.execute(
                    """
                    update service_credentials
                    set kernel_url = $1, updated_at = now()
                    where id = 1
                    """,
                    kernel_url,
                )
            else:
                await connection.execute(
                    """
                    update service_credentials
                    set kernel_url = $1,
                        kernel_token_ciphertext = $2,
                        updated_at = now()
                    where id = 1
                    """,
                    kernel_url,
                    kernel_token_ciphertext,
                )

    async def settings(self) -> dict[str, Any]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch("select key, value from app_settings")
        result = dict(DEFAULT_SETTINGS)
        for row in rows:
            key = str(row["key"])
            if key in DEFAULT_SETTINGS:
                result[key] = _json_value(row["value"])
        return result

    async def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for key, value in values.items():
                    await connection.execute(
                        """
                        insert into app_settings (key, value, updated_at)
                        values ($1, $2::jsonb, now())
                        on conflict (key) do update
                        set value = excluded.value, updated_at = now()
                        """,
                        key,
                        json.dumps(value),
                    )
        return await self.settings()

    async def begin_gryphon_event(self, event_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                inserted = await connection.fetchval(
                    """
                    insert into gryphon_events (event_id, state)
                    values ($1, 'processing')
                    on conflict do nothing
                    returning event_id
                    """,
                    event_id,
                )
                if inserted:
                    return None
                existing = await connection.fetchrow(
                    "select state, response from gryphon_events where event_id = $1 for update",
                    event_id,
                )
                if existing and existing["state"] == "completed":
                    return _json_value(existing["response"])
                if existing and existing["state"] == "failed":
                    await connection.execute(
                        """
                        update gryphon_events
                        set state = 'processing', response = null,
                            started_at = now(), completed_at = null
                        where event_id = $1
                        """,
                        event_id,
                    )
                    return None
                recovered = await connection.fetchval(
                    """
                    update gryphon_events
                    set started_at = now()
                    where event_id = $1 and state = 'processing'
                      and started_at < now() - interval '5 minutes'
                    returning event_id
                    """,
                    event_id,
                )
                if recovered:
                    return None
                raise RuntimeError("Gryphon event is already being processed")

    async def complete_gryphon_event(
        self, event_id: str, response: dict[str, Any]
    ) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                update gryphon_events
                set state = 'completed', response = $2::jsonb, completed_at = now()
                where event_id = $1 and state = 'processing'
                """,
                event_id,
                json.dumps(response),
            )

    async def fail_gryphon_event(self, event_id: str) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                update gryphon_events set state = 'failed', completed_at = now()
                where event_id = $1 and state = 'processing'
                """,
                event_id,
            )

    async def audit(
        self,
        *,
        status: str,
        action: str,
        target: str = "",
        actor: str = "system",
        message: str = "",
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                insert into audit_events
                    (status, action, target, actor, message, details, request_id)
                values ($1, $2, $3, $4, $5, $6::jsonb, $7)
                """,
                status,
                action,
                target,
                actor,
                message,
                json.dumps(details or {}),
                request_id,
            )
            await connection.execute(
                "delete from audit_events where created_at < now() - ($1 * interval '1 day')",
                self.audit_retention_days,
            )
            await connection.execute(
                """
                delete from audit_events where id in (
                    select id from audit_events
                    order by created_at desc
                    offset $1
                )
                """,
                self.audit_max_entries,
            )

    async def audit_events(
        self, limit: int = 200, *, after_id: int | None = None
    ) -> list[dict[str, Any]]:
        async with self.pool.acquire() as connection:
            if after_id is None:
                rows = await connection.fetch(
                    """
                    select id, status, action, target, actor, message, details,
                           request_id, created_at
                    from audit_events
                    order by id desc
                    limit $1
                    """,
                    max(1, min(limit, 10000)),
                )
            else:
                rows = await connection.fetch(
                    """
                    select id, status, action, target, actor, message, details,
                           request_id, created_at
                    from audit_events
                    where id > $1
                    order by id desc
                    limit $2
                    """,
                    max(0, after_id),
                    max(1, min(limit, 10000)),
                )
        return [
            {
                "id": int(row["id"]),
                "status": row["status"],
                "action": row["action"],
                "target": row["target"],
                "actor": row["actor"],
                "message": row["message"],
                "details": _json_value(row["details"]),
                "request_id": row["request_id"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    async def logical_backup(self) -> dict[str, Any]:
        owner = await self.owner()
        settings = await self.settings()
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                select id, public_id, user_id, category, started_at, stopped_at,
                       duration_seconds, carried_seconds, timer_group_key,
                       note, source, deleted_at
                from time_sessions
                where user_id = $1 and deleted_at is null
                order by started_at, id
                """,
                owner["id"],
            )
        return {
            "schema": "exocortex.chronos.backup.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "settings": settings,
            "sessions": [serialize_session(row) for row in rows],
        }

    async def restore_backup(self, backup: dict[str, Any]) -> int:
        if backup.get("schema") != "exocortex.chronos.backup.v1":
            raise ValueError("Unsupported Chronos backup schema")
        sessions = backup.get("sessions")
        settings = backup.get("settings")
        if not isinstance(sessions, list) or not isinstance(settings, dict):
            raise ValueError("Chronos backup is incomplete")
        if len(sessions) > 1_000_000:
            raise ValueError("Chronos backup contains too many sessions")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.owner(connection)
                await connection.execute(
                    "delete from time_sessions where user_id = $1", owner["id"]
                )
                for item in sessions:
                    if not isinstance(item, dict):
                        raise ValueError("Chronos backup contains an invalid session")
                    started = datetime.fromisoformat(str(item["started_at"]))
                    stopped = (
                        datetime.fromisoformat(str(item["stopped_at"]))
                        if item.get("stopped_at")
                        else None
                    )
                    await connection.execute(
                        """
                        insert into time_sessions
                            (public_id, user_id, category, started_at, stopped_at,
                             duration_seconds, carried_seconds, timer_group_key,
                             note, source)
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'restore')
                        """,
                        item.get("public_id"),
                        owner["id"],
                        item["category"],
                        started,
                        stopped,
                        item.get("duration_seconds"),
                        max(0, int(item.get("carried_seconds") or 0)),
                        item.get("timer_group_key"),
                        str(item.get("note") or "")[:500],
                    )
                for key, value in settings.items():
                    if key not in DEFAULT_SETTINGS:
                        continue
                    await connection.execute(
                        """
                        insert into app_settings (key, value, updated_at)
                        values ($1, $2::jsonb, now())
                        on conflict (key) do update
                        set value = excluded.value, updated_at = now()
                        """,
                        key,
                        json.dumps(value),
                    )
        return len(sessions)

    async def sessions_for_export(self) -> Iterable[asyncpg.Record]:
        owner = await self.owner()
        async with self.pool.acquire() as connection:
            return await connection.fetch(
                """
                select id, public_id, category, started_at, stopped_at, duration_seconds,
                       note, source
                from time_sessions
                where user_id = $1 and deleted_at is null
                order by started_at asc
                """,
                owner["id"],
            )
