from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.constants import CATEGORIES
from app.gryphon import GryphonClient, GryphonCommandService, GryphonError, format_duration
from app.updater import UpdaterClient


class FakeStore:
    def __init__(self) -> None:
        self.responses: dict[str, dict[str, Any]] = {}

    async def begin_gryphon_event(self, event_id: str):
        return self.responses.get(event_id)

    async def complete_gryphon_event(self, event_id: str, response: dict[str, Any]):
        self.responses[event_id] = response

    async def fail_gryphon_event(self, event_id: str):
        return None

    async def settings(self):
        return {"timezone": "UTC", "week_starts_on": 1}


class FakeTimers:
    def __init__(self) -> None:
        self.press_calls: list[str] = []

    async def press(self, category: str, **_: Any):
        self.press_calls.append(category)
        return {
            "action": "timer.started",
            "started": {
                "public_id": "t-00000001",
                "label": "Execution",
                "timer_elapsed_seconds": 0,
            },
            "stopped": None,
        }

    async def active(self):
        return None

    async def analytics(self, *_: Any):
        return {"total_seconds": 0, "categories": []}


def envelope(event_id: str, command: str, arguments: dict[str, Any] | None = None):
    return {
        "schema": "exocortex.telegram.command.v1",
        "eventId": event_id,
        "connectionId": "connection-1",
        "serviceId": "chronos",
        "actor": {
            "telegramUserId": "42",
            "chatId": "42",
            "chatType": "private",
        },
        "command": command,
        "arguments": arguments or {},
    }


@pytest.mark.asyncio
async def test_start_returns_all_categories_as_neutral_callback_actions():
    service = GryphonCommandService(FakeStore(), FakeTimers())  # type: ignore[arg-type]
    result = await service.handle(envelope("event-1", "start"))
    buttons = [button for row in result["actions"][0]["buttons"] for button in row]
    assert [button["arguments"]["category"] for button in buttons] == list(CATEGORIES)
    assert all(button["command"] == "press" for button in buttons)


@pytest.mark.asyncio
async def test_mutating_command_result_is_cached_by_gryphon_event_id():
    store = FakeStore()
    timers = FakeTimers()
    service = GryphonCommandService(store, timers)  # type: ignore[arg-type]
    command = envelope("event-2", "press", {"category": "execution"})

    first = await service.handle(command)
    second = await service.handle(command)

    assert first == second
    assert timers.press_calls == ["execution"]
    assert first["actions"][0]["text"] == "Started t-00000001 (Execution)."


@pytest.mark.asyncio
async def test_rejects_non_private_actor_before_mutating_state():
    timers = FakeTimers()
    service = GryphonCommandService(FakeStore(), timers)  # type: ignore[arg-type]
    command = envelope("event-3", "press", {"category": "execution"})
    command["actor"] = {
        "telegramUserId": "42",
        "chatId": "-42",
        "chatType": "group",
    }

    with pytest.raises(ValueError, match="private chat"):
        await service.handle(command)
    assert timers.press_calls == []


def test_format_duration_includes_all_nonzero_units():
    assert format_duration(90061) == "1d 1h 1m 1s"


@pytest.mark.asyncio
async def test_service_client_validates_identity_and_uses_scoped_routes(monkeypatch):
    client = GryphonClient("/run/gryphon/client.sock", Path("unused.token"), 1)
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(method: str, route: str, body: dict[str, Any] | None = None):
        calls.append((method, route, body))
        if route.endswith("/bots"):
            return {
                "schema": "exocortex.gryphon.service-bots.v1",
                "serviceId": "chronos",
                "bots": [{"id": "bot-1", "alias": "main", "state": "ready", "selected": False}],
            }
        if method == "DELETE":
            return {"disconnected": True}
        if route.endswith("notifications"):
            return {"accepted": True}
        return {
            "schema": "exocortex.gryphon.service-status.v1",
            "version": "1.2.3",
            "serviceId": "chronos",
            "state": "enabled",
            "connected": True,
            "commandPrefix": "chronos",
            "bot": {"id": "bot-1", "alias": "main", "state": "ready"},
            "binding": None,
        }

    monkeypatch.setattr(client, "_request", request)
    assert (await client.status())["version"] == "1.2.3"
    assert (await client.bots())["bots"][0]["id"] == "bot-1"
    assert (await client.connect("bot-1", "http://chronos/api/internal/gryphon/command"))["connected"] is True
    assert (await client.disconnect())["disconnected"] is True
    await client.notify("Summary", "summary-2026-09-09")
    assert calls == [
        ("GET", "/v1/service", None),
        ("GET", "/v1/service/bots", None),
        ("PUT", "/v1/service/connection", {"botId": "bot-1", "commandPrefix": "chronos", "adapterUrl": "http://chronos/api/internal/gryphon/command"}),
        ("DELETE", "/v1/service/connection", None),
        ("POST", "/v1/service/notifications", {"text": "Summary", "idempotencyKey": "summary-2026-09-09"}),
    ]


@pytest.mark.asyncio
async def test_service_client_rejects_cross_service_status(monkeypatch):
    client = GryphonClient("/run/gryphon/client.sock", Path("unused.token"), 1)
    monkeypatch.setattr(client, "_request", lambda *_: {
        "schema": "exocortex.gryphon.service-status.v1",
        "version": "1.2.3",
        "serviceId": "saturn",
        "connected": False,
        "bot": None,
        "binding": None,
    })
    with pytest.raises(GryphonError, match="invalid service status"):
        await client.status()


@pytest.mark.asyncio
async def test_updater_client_uses_gryphon_component_routes(monkeypatch):
    client = UpdaterClient("/run/exocortex/updater.sock", "control-token", "chronos")
    calls: list[tuple[str, str, dict[str, Any] | None, bool, float]] = []

    def request(
        _client: UpdaterClient,
        method: str,
        route: str,
        body: dict[str, Any] | None = None,
        authenticated: bool = False,
        timeout: float = 10,
    ):
        calls.append((method, route, body, authenticated, timeout))
        return {"update_available": route.endswith("/check")}

    monkeypatch.setattr(UpdaterClient, "_request", request)
    assert (await client.check_gryphon("1.2.3"))["update_available"] is True
    await client.update_gryphon("1.2.4")
    assert calls == [
        (
            "POST",
            "/v1/components/gryphon-linux/check",
            {"head_id": "chronos", "current_version": "1.2.3"},
            True,
            30,
        ),
        (
            "POST",
            "/v1/components/gryphon-linux/update",
            {"head_id": "chronos", "version": "1.2.4"},
            True,
            300,
        ),
    ]
