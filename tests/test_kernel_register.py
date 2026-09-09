from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from app.config import load_config
from app.kernel_register import _verify_snapshot, apply_register


class KernelResponse:
    def __init__(self, values: dict[str, str]) -> None:
        self.body = json.dumps(
            {
                "schema": "exocortex.register.resolution.v1",
                "register_revision": "register-000042",
                "values": {key: {"value": value, "secret": False, "volt_revision": 3} for key, value in values.items()},
            }
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.body


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


def reference(number: int) -> str:
    return f"volt://{number:08x}-1111-4111-8111-111111111111/{number:08x}-2222-4222-8222-222222222222"


def test_register_applies_chronos_runtime_values(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOS_ACCESS_KEY", "long-test-access-key")
    monkeypatch.setenv("CHRONOS_SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("KERNEL_URL", "https://kernel.example.com")
    monkeypatch.setenv("KERNEL_SERVICE_TOKEN", "kernel-test-token")
    config = load_config()
    resolved_values = {
        "repositories.chronos.url": "https://github.com/example/chronos",
        "services.chronos.sni": "chronos.example.com",
        "services.chronos.port": "443",
        "intervals.kernel.refresh_sec": "90",
    }
    references = {key: reference(index + 1) for index, key in enumerate(resolved_values)}
    data = snapshot(
        {
            "repositories": {"chronos": {"url": references["repositories.chronos.url"]}},
            "services": {
                "chronos": {
                    "sni": references["services.chronos.sni"],
                    "port": references["services.chronos.port"],
                },
            },
            "intervals": {"kernel": {"refresh_sec": references["intervals.kernel.refresh_sec"]}},
        }
    )
    def opener(request, timeout):
        assert request.full_url == "https://kernel.example.com/api/v1/register/resolve"
        assert request.headers["Authorization"] == "Bearer kernel-test-token"
        assert json.loads(request.data) == {"keys": list(resolved_values)}
        assert timeout == 3
        return KernelResponse(resolved_values)

    updated = apply_register(config, _verify_snapshot(data), kernel_opener=opener)
    assert updated.repository_url == "https://github.com/example/chronos"
    assert updated.public_url == "https://chronos.example.com"
    assert updated.kernel_refresh_seconds == 90
    assert updated.register_revision == "register-000042"


def test_register_rejects_environment_secret_reference(monkeypatch) -> None:
    config = load_config()
    data = snapshot(
        {
            "services": {
                "chronos": {
                    "url": "secret://env/CHRONOS_PUBLIC_URL",
                }
            }
        }
    )
    try:
        apply_register(config, data)
    except RuntimeError as error:
        assert "volt://" in str(error)
    else:
        raise AssertionError("environment secret references must be rejected")
