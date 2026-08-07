from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import asyncpg


Category = str


@dataclass(frozen=True)
class TimeSession:
    id: int
    user_id: int
    category: Category
    started_at: datetime
    stopped_at: datetime | None
    duration_seconds: int | None


async def ensure_user(conn: asyncpg.Connection, tg_user_id: int) -> int:
    row = await conn.fetchrow(
        """
        insert into users (tg_user_id)
        values ($1)
        on conflict (tg_user_id) do update
        set tg_user_id = excluded.tg_user_id
        returning id
        """,
        tg_user_id,
    )
    return int(row["id"])


async def get_active_session(
    conn: asyncpg.Connection, user_id: int
) -> TimeSession | None:
    row = await conn.fetchrow(
        """
        select id, user_id, category, started_at, stopped_at, duration_seconds
        from time_sessions
        where user_id = $1 and stopped_at is null
        order by started_at desc
        limit 1
        """,
        user_id,
    )
    if row is None:
        return None
    return TimeSession(
        id=row["id"],
        user_id=row["user_id"],
        category=row["category"],
        started_at=row["started_at"],
        stopped_at=row["stopped_at"],
        duration_seconds=row["duration_seconds"],
    )


async def create_session(
    conn: asyncpg.Connection,
    user_id: int,
    category: Category,
    started_at: datetime,
) -> TimeSession:
    row = await conn.fetchrow(
        """
        insert into time_sessions (user_id, category, started_at)
        values ($1, $2, $3)
        returning id, user_id, category, started_at, stopped_at, duration_seconds
        """,
        user_id,
        category,
        started_at,
    )
    return TimeSession(
        id=row["id"],
        user_id=row["user_id"],
        category=row["category"],
        started_at=row["started_at"],
        stopped_at=row["stopped_at"],
        duration_seconds=row["duration_seconds"],
    )


async def stop_session(
    conn: asyncpg.Connection,
    session_id: int,
    stopped_at: datetime,
    duration_seconds: int,
) -> TimeSession:
    row = await conn.fetchrow(
        """
        update time_sessions
        set stopped_at = $2, duration_seconds = $3
        where id = $1
        returning id, user_id, category, started_at, stopped_at, duration_seconds
        """,
        session_id,
        stopped_at,
        duration_seconds,
    )
    return TimeSession(
        id=row["id"],
        user_id=row["user_id"],
        category=row["category"],
        started_at=row["started_at"],
        stopped_at=row["stopped_at"],
        duration_seconds=row["duration_seconds"],
    )


async def list_sessions_for_period(
    conn: asyncpg.Connection,
    user_id: int,
    start: datetime,
    end: datetime,
) -> Iterable[TimeSession]:
    rows = await conn.fetch(
        """
        select id, user_id, category, started_at, stopped_at, duration_seconds
        from time_sessions
        where user_id = $1 and started_at >= $2 and started_at <= $3
        order by started_at asc
        """,
        user_id,
        start,
        end,
    )
    return [
        TimeSession(
            id=row["id"],
            user_id=row["user_id"],
            category=row["category"],
            started_at=row["started_at"],
            stopped_at=row["stopped_at"],
            duration_seconds=row["duration_seconds"],
        )
        for row in rows
    ]
