from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from app.config import load_config
from app.kernel_register import _verify_snapshot, apply_register


def snapshot(values: dict) -> dict:
    canonical = json.dumps(
        {"values": values}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return {
        "schema": "exocortex.register.snapshot.v1",
        "revision": "register-000042",
        "checksum": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        "values": values,
    }


def test_register_applies_chronos_runtime_values(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOS_ACCESS_KEY", "long-test-access-key")
    monkeypatch.setenv("CHRONOS_SESSION_SECRET", "x" * 40)
    config = load_config()
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    data = snapshot(
        {
            "repositories": {"chronos": {"url": "https://github.com/example/chronos"}},
            "services": {
                "chronos": {"sni": "chronos.example.com", "port": "443", "telegram_api": token}
            },
            "intervals": {"kernel": {"refresh_sec": "90"}},
        }
    )
    updated = apply_register(config, _verify_snapshot(data))
    assert updated.repository_url == "https://github.com/example/chronos"
    assert updated.public_url == "https://chronos.example.com"
    assert updated.telegram_token == token
    assert updated.kernel_refresh_seconds == 90
    assert updated.register_revision == "register-000042"


def test_register_can_resolve_local_secret_reference(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOS_TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef")
    config = replace(load_config(), telegram_token="")
    data = snapshot(
        {
            "services": {
                "chronos": {
                    "url": "https://chronos.example.com",
                    "telegram_api": "secret://env/CHRONOS_TELEGRAM_BOT_TOKEN",
                }
            }
        }
    )
    assert apply_register(config, data).telegram_token.startswith("123456789:")
