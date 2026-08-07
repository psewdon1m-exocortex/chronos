from __future__ import annotations

from pathlib import Path

import asyncpg


async def create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=database_url,
        min_size=1,
        max_size=10,
        command_timeout=30,
    )


async def run_migrations(pool: asyncpg.Pool, migrations_dir: Path) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            """
            create table if not exists schema_migrations (
                version text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        for migration in sorted(migrations_dir.glob("*.sql")):
            version = migration.name
            applied = await connection.fetchval(
                "select 1 from schema_migrations where version = $1", version
            )
            if applied:
                continue
            script = migration.read_text(encoding="utf-8")
            async with connection.transaction():
                await connection.execute(script)
                await connection.execute(
                    "insert into schema_migrations (version) values ($1)", version
                )

