from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import copy
import json
import re
from typing import Any, Iterable

import asyncpg

from .constants import DEFAULT_SETTINGS
from .security import hash_password
from .validation import validate_settings, validate_session
from .transactions import TransactionPool


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _redact_audit(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k)[:120]: "[redacted]" if re.search(r"token|secret|password|authorization|cookie|access.?key", str(k), re.I) else _redact_audit(v) for k, v in list(value.items())[:64]}
    if isinstance(value, (list, tuple)): return [_redact_audit(v) for v in value[:64]]
    if isinstance(value, str): return re.sub(r"(?i)(bearer\s+|volt://)\S+", "[redacted]", value)[:2048]
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
        self.pool = TransactionPool(pool)
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

    async def session_revoked(self, token: str) -> bool:
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self.pool.acquire() as connection:
            return bool(await connection.fetchval(
                "select 1 from revoked_sessions where token_hash = $1 and expires_at > now()", digest
            ))

    async def revoke_session(self, token: str, expires_at: int) -> None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("delete from revoked_sessions where expires_at <= now()")
                await connection.execute(
                    "insert into revoked_sessions(token_hash, expires_at) values ($1, $2) on conflict do nothing",
                    digest, datetime.fromtimestamp(expires_at, timezone.utc),
                )

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
                if await connection.fetchval("select count(*) >= 100000 and not exists (select 1 from gryphon_events where event_id=$1) from gryphon_events", event_id):
                    raise RuntimeError("Command replay journal capacity reached; retry after retention pruning")
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
                json.dumps(_redact_audit(details or {})),
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
            await connection.execute("""
                delete from audit_events where id in (
                    select id from (select id, sum(pg_column_size(audit_events)) over(order by id desc) as bytes from audit_events) bounded where bytes > 67108864
                )
            """)
            # Undo and command replay retention have the same declared 30-day window.
            await connection.execute("delete from undo_actions where created_at < now() - interval '30 days'")
            await connection.execute("delete from gryphon_events where state != 'processing' and created_at < now() - interval '30 days'")
            await connection.execute("delete from undo_actions where id not in (select id from undo_actions order by id desc limit 10000)")

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
        async with self.pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                owner = await self.owner(connection)
                rows = await connection.fetch("select * from time_sessions where user_id=$1 order by id", owner["id"])
                settings = {row["key"]: _json_value(row["value"]) for row in await connection.fetch("select key,value from app_settings")}
                security = dict(await connection.fetchrow("select password_hash, session_generation from operator_security where id=1"))
                kernel_url = await connection.fetchval("select kernel_url from service_credentials where id=1")
                undo = [dict(row) for row in await connection.fetch(
                    "select action,before_state,after_ids,used_at,created_at from undo_actions where user_id=$1 order by id", owner["id"]
                )]
                events = [dict(row) for row in await connection.fetch("select * from gryphon_events order by created_at")]
        def portable(value):
            if isinstance(value, datetime): return value.isoformat()
            if isinstance(value, dict): return {key: portable(item) for key, item in value.items()}
            if isinstance(value, list): return [portable(item) for item in value]
            return value
        return {
            "schema": "exocortex.chronos.backup.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "settings": settings,
            "sessions": [serialize_session(row) for row in rows],
            "recovery": {
                "version": 1,
                "security": security,
                "kernel_url": kernel_url,
                "credentials_policy": "retain-target-enrollment",
                "sessions_policy": "revoke-all",
                "undo_actions": portable(undo),
                "gryphon_events": portable(events),
            },
        }

    async def restore_backup(self, backup: dict[str, Any]) -> int:
        if backup.get("schema") != "exocortex.chronos.backup.v1":
            raise ValueError("Unsupported Chronos backup schema")
        sessions = backup.get("sessions")
        raw_settings = backup.get("settings")
        if not isinstance(sessions, list) or not isinstance(raw_settings, dict):
            raise ValueError("Chronos backup is incomplete")
        if len(sessions) > 1_000_000:
            raise ValueError("Chronos backup contains too many sessions")
        settings = {**DEFAULT_SETTINGS, **validate_settings(raw_settings)}
        sessions = [validate_session(item) for item in sessions]
        if len({item["id"] for item in sessions}) != len(sessions) or len({item["public_id"] for item in sessions}) != len(sessions):
            raise ValueError("Duplicate backup session identity")
        if sum(item["stopped_at"] is None and item["deleted_at"] is None for item in sessions) > 1:
            raise ValueError("Backup has more than one active timer")
        recovery = copy.deepcopy(backup.get("recovery") or {})
        if not isinstance(recovery, dict) or (recovery and recovery.get("version") != 1):
            raise ValueError("Unsupported recovery metadata")
        security = recovery.get("security")
        if security is not None and (
            not isinstance(security, dict)
            or not re.fullmatch(r"scrypt\$[A-Za-z0-9_-]{22}\$[A-Za-z0-9_-]{86}", str(security.get("password_hash", "")))
            or type(security.get("session_generation")) is not int
            or not 0 < security["session_generation"] < 2**30
        ):
            raise ValueError("Invalid recovery access verifier")
        undo = recovery.get("undo_actions", [])
        events = recovery.get("gryphon_events", [])
        if not isinstance(undo, list) or not isinstance(events, list) or len(undo) > 10000 or len(events) > 100000:
            raise ValueError("Invalid recovery event inventory")
        def stamp(value):
            if value is None: return None
            try: parsed = datetime.fromisoformat(value)
            except (ValueError, TypeError) as error: raise ValueError("Invalid recovery timestamp") from error
            if parsed.tzinfo is None: raise ValueError("Recovery timestamps require timezone")
            return parsed
        for item in undo:
            if not isinstance(item, dict) or not isinstance(item.get("action"), str) or len(item["action"]) > 100:
                raise ValueError("Invalid undo action")
            before, after = _json_value(item.get("before_state")), _json_value(item.get("after_ids"))
            if not isinstance(before, list) or not isinstance(after, list) or len(before) > 10000 or len(after) > 10000:
                raise ValueError("Invalid undo references")
            for session in before: validate_session(session)
            if any(type(identifier) is not int or identifier <= 0 or identifier >= 2**63-1 for identifier in after):
                raise ValueError("Invalid undo ID")
            item["before_state"], item["after_ids"] = before, after
            item["created_at"], item["used_at"] = stamp(item.get("created_at")), stamp(item.get("used_at"))
            if item["created_at"] is None: raise ValueError("Missing undo timestamp")
        event_ids = set()
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not 0 < len(event["event_id"]) <= 200 or event["event_id"] in event_ids:
                raise ValueError("Invalid Gryphon event identity")
            event_ids.add(event["event_id"])
            if event.get("state") not in {"processing", "completed", "failed"}: raise ValueError("Invalid Gryphon event state")
            if event["state"] == "processing":
                # Old releases could commit a timer separately from their journal.
                # An uncertain restored command must never mutate that timer twice.
                event["state"] = "completed"
                event["response"] = {"schema": "exocortex.telegram.response.v1", "actions": [{"type": "send_message", "text": "This command was interrupted before recovery. Check the timer state and submit a new command if needed."}]}
            for key in ("created_at", "started_at", "completed_at"): event[key] = stamp(event.get(key))
            if event["created_at"] is None or event["started_at"] is None: raise ValueError("Missing Gryphon event timestamp")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                await connection.execute("delete from undo_actions where user_id=$1", owner["id"])
                await connection.execute(
                    "delete from time_sessions where user_id = $1", owner["id"]
                )
                for item in sessions:
                    await connection.execute(
                        """
                        insert into time_sessions
                            (id, public_id, user_id, category, started_at, stopped_at,
                             duration_seconds, carried_seconds, timer_group_key,
                             note, source, deleted_at)
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        """,
                        item["id"], item["public_id"],
                        owner["id"],
                        item["category"],
                        item["started_at"],
                        item["stopped_at"],
                        item.get("duration_seconds"),
                        max(0, int(item.get("carried_seconds") or 0)),
                        item.get("timer_group_key"),
                        item.get("note", ""), item.get("source", "restore"), item["deleted_at"],
                    )
                for key, value in settings.items():
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
                for item in undo:
                    for row in item["before_state"]: row["user_id"] = owner["id"]
                    await connection.execute(
                        "insert into undo_actions(user_id,action,before_state,after_ids,used_at,created_at) values($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
                        owner["id"],item["action"],json.dumps(item["before_state"]),json.dumps(item["after_ids"]),item["used_at"],item["created_at"],
                    )
                await connection.execute("delete from gryphon_events")
                for event in events:
                    await connection.execute(
                        "insert into gryphon_events(event_id,state,response,created_at,started_at,completed_at) values($1,$2,$3::jsonb,$4,$5,$6)",
                        event["event_id"], event["state"],
                        json.dumps(_json_value(event.get("response"))), event["created_at"], event["started_at"], event["completed_at"],
                    )
                await connection.execute(
                    "update operator_security set password_hash=coalesce($1,password_hash), session_generation=greatest(session_generation,$2)+1, updated_at=now() where id=1",
                    security["password_hash"] if security else None, security["session_generation"] if security else 0,
                )
                await connection.execute("delete from revoked_sessions")
                # Explicit restored IDs and legacy public IDs must both be below the next allocation.
                maximum = max([item["id"] for item in sessions] + [int(item["public_id"][2:]) for item in sessions] + [0])
                await connection.execute("select setval(pg_get_serial_sequence('time_sessions','id'), $1, $2)", max(1, maximum), maximum > 0)
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
