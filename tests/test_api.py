from __future__ import annotations

import os
import re
import asyncio
import asyncpg

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


def test_health_login_and_protected_dashboard(monkeypatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL", "")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not database_url.rstrip("/").endswith("chronos_test"):
        raise RuntimeError("TEST_DATABASE_URL must identify the chronos_test database")
    async def reset_test_database():
        connection = await asyncpg.connect(database_url)
        try:
            await connection.execute("drop schema public cascade; create schema public")
        finally:
            await connection.close()
    asyncio.run(reset_test_database())
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("CHRONOS_ACCESS_KEY", "test-access-key-long-enough")
    monkeypatch.setenv("CHRONOS_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("CHRONOS_COOKIE_SECURE", "false")
    monkeypatch.delenv("KERNEL_URL", raising=False)
    monkeypatch.delenv("KERNEL_SERVICE_TOKEN", raising=False)
    with TestClient(create_app()) as client:
        robots = client.get("/robots.txt")
        assert robots.text == "User-agent: *\nDisallow: /\n"
        assert robots.headers["x-robots-tag"] == "noindex, nofollow, noarchive, nosnippet"
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/health").json()["status"] == "available"
        assert client.get(
            "/api/health", headers={"X-Forwarded-For": "203.0.113.10"}
        ).status_code == 404
        for probe in ("/.env", "/wp-admin", "/phpmyadmin", "/.git/config"):
            probe_response = client.get(probe)
            assert probe_response.status_code == 404
            assert probe_response.json() == {"error": "Not found"}
        assert client.get("/api/dashboard").status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"access_key": "test-access-key-long-enough"},
        )
        assert login.status_code == 200
        csrf = client.cookies.get("chronos_csrf")
        assert csrf
        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.headers["cache-control"] == "no-store"
        assert dashboard.headers["x-robots-tag"] == "noindex, nofollow, noarchive, nosnippet"
        assert set(dashboard.json()["telemetry"]) == {
            "captured_at",
            "cpu",
            "ram",
            "disk",
            "uptime_seconds",
        }
        assert [item["key"] for item in dashboard.json()["categories"]] == [
            "recovery",
            "accumulation",
            "execution",
            "maintenance",
        ]
        press = client.post(
            "/api/timer/press",
            json={"category": "execution"},
            headers={"X-CSRF-Token": csrf},
        )
        assert press.status_code == 200
        assert press.json()["started"]["category"] == "execution"
        assert re.fullmatch(r"t-\d{8,}", press.json()["started"]["public_id"])
