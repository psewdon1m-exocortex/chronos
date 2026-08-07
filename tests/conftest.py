from __future__ import annotations

import os
from pathlib import Path

import asyncpg
import pytest_asyncio

from app.database import create_pool, run_migrations
from app.store import Store


@pytest_asyncio.fixture
async def store() -> Store:
    database_url = os.getenv("TEST_DATABASE_URL", "")
    if not database_url:
        import pytest

        pytest.skip("TEST_DATABASE_URL is not configured")
    if not database_url.rstrip("/").endswith("chronos_test"):
        raise RuntimeError("TEST_DATABASE_URL must identify the chronos_test database")
    admin = await asyncpg.connect(database_url)
    try:
        await admin.execute("drop schema public cascade")
        await admin.execute("create schema public")
    finally:
        await admin.close()
    pool = await create_pool(database_url)
    await run_migrations(
        pool,
        Path(__file__).resolve().parents[1] / "infrastructure" / "migrations",
    )
    result = Store(pool, audit_max_entries=1000, audit_retention_days=30)
    await result.initialize(
        admin_username="test-operator",
        admin_password="test-password-long-enough",
        default_timezone="UTC",
    )
    try:
        yield result
    finally:
        await pool.close()

