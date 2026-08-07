from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


def test_health_login_and_protected_dashboard(monkeypatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL", "")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("CHRONOS_ADMIN_USERNAME", "test-operator")
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "test-password-long-enough")
    monkeypatch.setenv("CHRONOS_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("CHRONOS_COOKIE_SECURE", "false")
    monkeypatch.delenv("KERNEL_URL", raising=False)
    monkeypatch.delenv("KERNEL_SERVICE_TOKEN", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["status"] == "available"
        assert client.get("/api/dashboard").status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"username": "test-operator", "password": "test-password-long-enough"},
        )
        assert login.status_code == 200
        csrf = client.cookies.get("chronos_csrf")
        assert csrf
        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200
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

