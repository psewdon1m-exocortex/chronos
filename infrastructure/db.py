from __future__ import annotations

import asyncpg

from infrastructure.config import DbConfig


def build_dsn(db: DbConfig) -> str:
    user = db.user
    password = db.password
    if password:
        auth = f"{user}:{password}"
    else:
        auth = user
    return (
        f"postgresql://{auth}@{db.host}:{db.port}/{db.name}"
        f"?sslmode={db.sslmode}"
    )


async def create_pool(db: DbConfig) -> asyncpg.Pool:
    dsn = build_dsn(db)
    return await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
