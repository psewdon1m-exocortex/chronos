from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg

from .constants import CATEGORIES, CATEGORY_LABELS, normalize_category
from .store import Store, serialize_session


class TimerError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def timezone_for(value: str) -> tzinfo:
    if value == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise TimerError("Timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def _effective_duration(row: asyncpg.Record | dict[str, Any], now: datetime) -> int:
    end = row["stopped_at"] or now
    return max(0, int((end - row["started_at"]).total_seconds()))


def present_session(row: asyncpg.Record, now: datetime) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "public_id": str(row["public_id"]),
        "category": row["category"],
        "label": CATEGORY_LABELS[row["category"]],
        "started_at": row["started_at"].isoformat(),
        "stopped_at": row["stopped_at"].isoformat() if row["stopped_at"] else None,
        "duration_seconds": _effective_duration(row, now),
        "note": row["note"],
        "source": row["source"],
        "active": row["stopped_at"] is None,
        "updated_at": row["updated_at"].isoformat(),
    }


class TimerService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def _active(
        self, connection: asyncpg.Connection, user_id: int, for_update: bool = False
    ) -> asyncpg.Record | None:
        suffix = " for update" if for_update else ""
        return await connection.fetchrow(
            """
            select id, public_id, user_id, category, started_at, stopped_at,
                   duration_seconds, note, source, updated_at, deleted_at
            from time_sessions
            where user_id = $1 and stopped_at is null and deleted_at is null
            order by started_at desc, id desc
            limit 1
            """ + suffix,
            user_id,
        )

    async def active(self, now: datetime | None = None) -> dict[str, Any] | None:
        current = now or datetime.now(timezone.utc)
        owner = await self.store.owner()
        async with self.store.pool.acquire() as connection:
            row = await self._active(connection, owner["id"])
        return present_session(row, current) if row else None

    async def _record_undo(
        self,
        connection: asyncpg.Connection,
        *,
        user_id: int,
        action: str,
        before: list[dict[str, Any]],
        after_ids: list[int],
    ) -> None:
        await connection.execute(
            "update undo_actions set used_at = now() where user_id = $1 and used_at is null",
            user_id,
        )
        await connection.execute(
            """
            insert into undo_actions (user_id, action, before_state, after_ids)
            values ($1, $2, $3::jsonb, $4::jsonb)
            """,
            user_id,
            action,
            json.dumps(before),
            json.dumps(after_ids),
        )

    async def press(
        self,
        category: str,
        *,
        actor: str,
        source: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        category = normalize_category(category)
        current = _aware(now or datetime.now(timezone.utc))
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                active = await self._active(connection, owner["id"], True)
                before = [serialize_session(active)] if active else []
                touched: list[int] = []
                stopped: asyncpg.Record | None = None
                started: asyncpg.Record | None = None
                if active:
                    stopped = await connection.fetchrow(
                        """
                        update time_sessions
                        set stopped_at = $2,
                            duration_seconds = greatest(0, extract(epoch from ($2 - started_at))::integer),
                            updated_at = now()
                        where id = $1
                        returning *
                        """,
                        active["id"],
                        current,
                    )
                    touched.append(int(active["id"]))
                if not active or active["category"] != category:
                    started = await connection.fetchrow(
                        """
                        insert into time_sessions
                            (user_id, category, started_at, note, source)
                        values ($1, $2, $3, '', $4)
                        returning *
                        """,
                        owner["id"],
                        category,
                        current,
                        source,
                    )
                    touched.append(int(started["id"]))
                action = (
                    "timer.started"
                    if active is None
                    else "timer.stopped"
                    if started is None
                    else "timer.switched"
                )
                await self._record_undo(
                    connection,
                    user_id=owner["id"],
                    action=action,
                    before=before,
                    after_ids=touched,
                )
        await self.store.audit(
            status="success",
            action=action,
            target=category,
            actor=actor,
            message=f"{CATEGORY_LABELS[category]} timer state changed",
        )
        return {
            "action": action,
            "stopped": present_session(stopped, current) if stopped else None,
            "started": present_session(started, current) if started else None,
        }

    async def stop(
        self, *, actor: str, now: datetime | None = None
    ) -> dict[str, Any] | None:
        current = _aware(now or datetime.now(timezone.utc))
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                active = await self._active(connection, owner["id"], True)
                if active is None:
                    return None
                stopped = await connection.fetchrow(
                    """
                    update time_sessions
                    set stopped_at = $2,
                        duration_seconds = greatest(0, extract(epoch from ($2 - started_at))::integer),
                        updated_at = now()
                    where id = $1
                    returning *
                    """,
                    active["id"],
                    current,
                )
                await self._record_undo(
                    connection,
                    user_id=owner["id"],
                    action="timer.stopped",
                    before=[serialize_session(active)],
                    after_ids=[int(active["id"])],
                )
        await self.store.audit(
            status="success",
            action="timer.stopped",
            target=active["category"],
            actor=actor,
            message="Active timer stopped",
        )
        return present_session(stopped, current)

    async def _overlap(
        self,
        connection: asyncpg.Connection,
        user_id: int,
        start: datetime,
        end: datetime | None,
        exclude_id: int | None = None,
    ) -> bool:
        return bool(
            await connection.fetchval(
                """
                select 1 from time_sessions
                where user_id = $1
                  and deleted_at is null
                  and ($4::bigint is null or time_sessions.id <> $4::bigint)
                  and started_at < coalesce($3::timestamptz, 'infinity'::timestamptz)
                  and coalesce(stopped_at, 'infinity'::timestamptz) > $2
                limit 1
                """,
                user_id,
                start,
                end,
                exclude_id,
            )
        )

    async def create_manual(
        self,
        *,
        category: str,
        started_at: datetime,
        stopped_at: datetime,
        note: str,
        actor: str,
    ) -> dict[str, Any]:
        category = normalize_category(category)
        start = _aware(started_at)
        end = _aware(stopped_at)
        if end <= start:
            raise TimerError("Session end must be later than its start")
        if end - start > timedelta(days=7):
            raise TimerError("A single session cannot exceed seven days")
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                if await self._overlap(connection, owner["id"], start, end):
                    raise TimerError("Session overlaps an existing entry", 409)
                row = await connection.fetchrow(
                    """
                    insert into time_sessions
                        (user_id, category, started_at, stopped_at,
                         duration_seconds, note, source)
                    values ($1, $2, $3, $4,
                            extract(epoch from ($4::timestamptz - $3::timestamptz))::integer,
                            $5, 'manual')
                    returning *
                    """,
                    owner["id"],
                    category,
                    start,
                    end,
                    note.strip()[:500],
                )
                await self._record_undo(
                    connection,
                    user_id=owner["id"],
                    action="session.created",
                    before=[],
                    after_ids=[int(row["id"])],
                )
        await self.store.audit(
            status="success",
            action="session.created",
            target=str(row["id"]),
            actor=actor,
            message="Manual session created",
        )
        return present_session(row, datetime.now(timezone.utc))

    async def last_completed(
        self, now: datetime | None = None
    ) -> dict[str, Any] | None:
        current = _aware(now or datetime.now(timezone.utc))
        owner = await self.store.owner()
        async with self.store.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select * from time_sessions
                where user_id = $1 and stopped_at is not null and deleted_at is null
                order by stopped_at desc, started_at desc, id desc
                limit 1
                """,
                owner["id"],
            )
        return present_session(row, current) if row else None

    async def retype_last_completed(
        self,
        category: str,
        *,
        actor: str,
        expected_public_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        category = normalize_category(category)
        current = _aware(now or datetime.now(timezone.utc))
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                existing = await connection.fetchrow(
                    """
                    select * from time_sessions
                    where user_id = $1 and stopped_at is not null and deleted_at is null
                    order by stopped_at desc, started_at desc, id desc
                    limit 1
                    for update
                    """,
                    owner["id"],
                )
                if existing is None:
                    raise TimerError("There is no completed session to change", 404)
                if (
                    expected_public_id is not None
                    and existing["public_id"] != expected_public_id
                ):
                    raise TimerError(
                        "The last completed session changed; run /retype again",
                        409,
                    )
                row = await connection.fetchrow(
                    """
                    update time_sessions
                    set category = $2, updated_at = now()
                    where id = $1
                    returning *
                    """,
                    existing["id"],
                    category,
                )
                await self._record_undo(
                    connection,
                    user_id=owner["id"],
                    action="session.retyped",
                    before=[serialize_session(existing)],
                    after_ids=[int(existing["id"])],
                )
        await self.store.audit(
            status="success",
            action="session.retyped",
            target=str(row["public_id"]),
            actor=actor,
            message="Last completed session category changed",
        )
        return present_session(row, current)

    async def backfill_active(
        self,
        category: str,
        minutes: int,
        *,
        actor: str,
        source: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        category = normalize_category(category)
        if minutes < 1 or minutes > 10080:
            raise TimerError("Minutes must be between 1 and 10080")
        current = _aware(now or datetime.now(timezone.utc))
        start = current - timedelta(minutes=minutes)
        trimmed: list[str] = []
        deleted: list[str] = []
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                overlaps = await connection.fetch(
                    """
                    select * from time_sessions
                    where user_id = $1 and deleted_at is null
                      and coalesce(stopped_at, 'infinity'::timestamptz) > $2
                    order by started_at, id
                    for update
                    """,
                    owner["id"],
                    start,
                )
                before = [serialize_session(row) for row in overlaps]
                touched: list[int] = []
                for existing in overlaps:
                    session_id = int(existing["id"])
                    touched.append(session_id)
                    if existing["started_at"] < start:
                        await connection.execute(
                            """
                            update time_sessions
                            set stopped_at = $2,
                                duration_seconds = greatest(
                                    0,
                                    extract(epoch from ($2 - started_at))::integer
                                ),
                                updated_at = now()
                            where id = $1
                            """,
                            session_id,
                            start,
                        )
                        trimmed.append(str(existing["public_id"]))
                    else:
                        await connection.execute(
                            """
                            update time_sessions
                            set deleted_at = now(), updated_at = now()
                            where id = $1
                            """,
                            session_id,
                        )
                        deleted.append(str(existing["public_id"]))
                started = await connection.fetchrow(
                    """
                    insert into time_sessions
                        (user_id, category, started_at, note, source)
                    values ($1, $2, $3, '', $4)
                    returning *
                    """,
                    owner["id"],
                    category,
                    start,
                    source,
                )
                touched.append(int(started["id"]))
                await self._record_undo(
                    connection,
                    user_id=owner["id"],
                    action="timer.backfilled",
                    before=before,
                    after_ids=touched,
                )
        await self.store.audit(
            status="success",
            action="timer.backfilled",
            target=str(started["public_id"]),
            actor=actor,
            message=f"Timer started {minutes} minutes in the past",
            details={"trimmed": trimmed, "deleted": deleted},
        )
        return {
            "started": present_session(started, current),
            "trimmed_ids": trimmed,
            "deleted_ids": deleted,
        }

    async def update_session(
        self,
        session_id: int,
        *,
        category: str,
        started_at: datetime,
        stopped_at: datetime | None,
        note: str,
        actor: str,
    ) -> dict[str, Any]:
        category = normalize_category(category)
        start = _aware(started_at)
        end = _aware(stopped_at) if stopped_at else None
        if end is not None and end <= start:
            raise TimerError("Session end must be later than its start")
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                existing = await connection.fetchrow(
                    """
                    select * from time_sessions
                    where id = $1 and user_id = $2 and deleted_at is null
                    for update
                    """,
                    session_id,
                    owner["id"],
                )
                if existing is None:
                    raise TimerError("Session not found", 404)
                if await self._overlap(
                    connection, owner["id"], start, end, exclude_id=session_id
                ):
                    raise TimerError("Session overlaps an existing entry", 409)
                row = await connection.fetchrow(
                    """
                    update time_sessions
                    set category = $2,
                        started_at = $3,
                        stopped_at = $4::timestamptz,
                        duration_seconds = case when $4::timestamptz is null then null
                            else extract(epoch from
                                ($4::timestamptz - $3::timestamptz))::integer end,
                        note = $5,
                        updated_at = now()
                    where id = $1
                    returning *
                    """,
                    session_id,
                    category,
                    start,
                    end,
                    note.strip()[:500],
                )
                await self._record_undo(
                    connection,
                    user_id=owner["id"],
                    action="session.updated",
                    before=[serialize_session(existing)],
                    after_ids=[session_id],
                )
        await self.store.audit(
            status="success",
            action="session.updated",
            target=str(session_id),
            actor=actor,
            message="Session updated",
        )
        return present_session(row, datetime.now(timezone.utc))

    async def delete_session(self, session_id: int, *, actor: str) -> None:
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                existing = await connection.fetchrow(
                    """
                    select * from time_sessions
                    where id = $1 and user_id = $2 and deleted_at is null
                    for update
                    """,
                    session_id,
                    owner["id"],
                )
                if existing is None:
                    raise TimerError("Session not found", 404)
                await connection.execute(
                    "update time_sessions set deleted_at = now(), updated_at = now() where id = $1",
                    session_id,
                )
                await self._record_undo(
                    connection,
                    user_id=owner["id"],
                    action="session.deleted",
                    before=[serialize_session(existing)],
                    after_ids=[session_id],
                )
        await self.store.audit(
            status="success",
            action="session.deleted",
            target=str(session_id),
            actor=actor,
            message="Session deleted",
        )

    async def undo(self, *, actor: str) -> dict[str, Any]:
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                owner = await self.store.owner(connection)
                await connection.execute("select pg_advisory_xact_lock($1)", owner["id"])
                action = await connection.fetchrow(
                    """
                    select * from undo_actions
                    where user_id = $1 and used_at is null
                    order by created_at desc
                    limit 1
                    for update
                    """,
                    owner["id"],
                )
                if action is None:
                    raise TimerError("There is no action to undo", 409)
                after_ids = action["after_ids"]
                if isinstance(after_ids, str):
                    after_ids = json.loads(after_ids)
                if after_ids:
                    await connection.execute(
                        """
                        update time_sessions
                        set deleted_at = now(), updated_at = now()
                        where user_id = $1 and id = any($2::bigint[])
                        """,
                        owner["id"],
                        [int(value) for value in after_ids],
                    )
                before_state = action["before_state"]
                if isinstance(before_state, str):
                    before_state = json.loads(before_state)
                restored: list[int] = []
                for item in before_state:
                    await connection.execute(
                        """
                        insert into time_sessions
                            (id, public_id, user_id, category, started_at, stopped_at,
                             duration_seconds, note, source, deleted_at, updated_at)
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
                        on conflict (id) do update
                        set public_id = excluded.public_id,
                            category = excluded.category,
                            started_at = excluded.started_at,
                            stopped_at = excluded.stopped_at,
                            duration_seconds = excluded.duration_seconds,
                            note = excluded.note,
                            source = excluded.source,
                            deleted_at = excluded.deleted_at,
                            updated_at = now()
                        """,
                        int(item["id"]),
                        item.get("public_id"),
                        owner["id"],
                        item["category"],
                        datetime.fromisoformat(item["started_at"]),
                        datetime.fromisoformat(item["stopped_at"])
                        if item.get("stopped_at")
                        else None,
                        item.get("duration_seconds"),
                        item.get("note", ""),
                        item.get("source", "web"),
                        datetime.fromisoformat(item["deleted_at"])
                        if item.get("deleted_at")
                        else None,
                    )
                    restored.append(int(item["id"]))
                await connection.execute(
                    "update undo_actions set used_at = now() where id = $1", action["id"]
                )
        await self.store.audit(
            status="success",
            action="action.undone",
            target=str(action["action"]),
            actor=actor,
            message="Last timer action was undone",
        )
        return {"undone": action["action"], "restored_ids": restored}

    async def history(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        category: str | None,
        query: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        owner = await self.store.owner()
        filters = ["user_id = $1", "deleted_at is null"]
        values: list[Any] = [owner["id"]]
        if start:
            values.append(_aware(start))
            filters.append(f"coalesce(stopped_at, 'infinity'::timestamptz) > ${len(values)}")
        if end:
            values.append(_aware(end))
            filters.append(f"started_at < ${len(values)}")
        if category:
            values.append(normalize_category(category))
            filters.append(f"category = ${len(values)}")
        if query.strip():
            values.append(f"%{query.strip()}%")
            filters.append(f"note ilike ${len(values)}")
        where = " and ".join(filters)
        async with self.store.pool.acquire() as connection:
            total = await connection.fetchval(
                f"select count(*) from time_sessions where {where}", *values
            )
            rows = await connection.fetch(
                f"""
                select * from time_sessions where {where}
                order by started_at desc, id desc
                limit ${len(values) + 1} offset ${len(values) + 2}
                """,
                *values,
                max(1, min(limit, 500)),
                max(0, offset),
            )
        now = datetime.now(timezone.utc)
        return {
            "items": [present_session(row, now) for row in rows],
            "total": int(total),
            "limit": max(1, min(limit, 500)),
            "offset": max(0, offset),
        }

    async def analytics(
        self, start: datetime, end: datetime, now: datetime | None = None
    ) -> dict[str, Any]:
        period_zone = start.tzinfo
        start = _aware(start)
        end = _aware(end)
        if end <= start:
            raise TimerError("Analytics end must be later than its start")
        if end - start > timedelta(days=370):
            raise TimerError("Analytics period cannot exceed 370 days")
        current = _aware(now or datetime.now(timezone.utc))
        owner = await self.store.owner()
        async with self.store.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                select * from time_sessions
                where user_id = $1 and deleted_at is null
                  and started_at < $3
                  and coalesce(stopped_at, $4) > $2
                order by started_at
                """,
                owner["id"],
                start,
                end,
                current,
            )
        totals = {category: 0 for category in CATEGORIES}
        daily: dict[str, dict[str, int]] = {}
        for row in rows:
            session_start = max(row["started_at"], start)
            session_end = min(row["stopped_at"] or current, end)
            if session_end <= session_start:
                continue
            totals[row["category"]] += int((session_end - session_start).total_seconds())
            cursor = session_start
            while cursor < session_end:
                local_cursor = cursor.astimezone(period_zone)
                day_end = datetime.combine(
                    local_cursor.date() + timedelta(days=1),
                    time.min,
                    tzinfo=period_zone,
                ).astimezone(timezone.utc)
                chunk_end = min(day_end, session_end)
                key = local_cursor.date().isoformat()
                bucket = daily.setdefault(key, {category: 0 for category in CATEGORIES})
                bucket[row["category"]] += int((chunk_end - cursor).total_seconds())
                cursor = chunk_end
        total_seconds = sum(totals.values())
        categories = [
            {
                "category": category,
                "label": CATEGORY_LABELS[category],
                "seconds": totals[category],
                "percent": round(totals[category] * 100 / total_seconds, 2)
                if total_seconds
                else 0.0,
            }
            for category in CATEGORIES
        ]
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total_seconds": total_seconds,
            "categories": categories,
            "days": [
                {"date": key, "total_seconds": sum(values.values()), "categories": values}
                for key, values in sorted(daily.items())
            ],
        }

    async def period_for_dates(
        self, start_date: date, end_date: date, timezone_name: str
    ) -> tuple[datetime, datetime]:
        zone = timezone_for(timezone_name)
        return (
            datetime.combine(start_date, time.min, tzinfo=zone),
            datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone),
        )
