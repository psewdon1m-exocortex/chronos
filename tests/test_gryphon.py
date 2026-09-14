from __future__ import annotations

import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.constants import CATEGORIES
from app.gryphon import (
    CHRONOS_COMMAND_CATALOG,
    GryphonClient,
    GryphonCommandService,
    GryphonError,
    format_duration,
)
from app.updater import UpdaterClient


class FakeStore:
    def __init__(self) -> None:
        self.responses: dict[str, dict[str, Any]] = {}
        self.pool = self

    @asynccontextmanager
    async def command(self):
        yield

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
async def test_timer_menu_returns_all_categories_as_persistent_keyboard_actions():
    service = GryphonCommandService(FakeStore(), FakeTimers())  # type: ignore[arg-type]
    result = await service.handle(envelope("event-1", "menu"))
    keyboard = result["actions"][0]["replyKeyboard"]
    buttons = [button for row in keyboard["rows"] for button in row]
    assert [button["arguments"]["category"] for button in buttons] == list(CATEGORIES)
    assert all(button["command"] == "press" for button in buttons)
    assert keyboard["persistent"] is True
    assert keyboard["resize"] is True


@pytest.mark.asyncio
async def test_each_persistent_keyboard_button_reaches_the_timer_service():
    timers = FakeTimers()
    service = GryphonCommandService(FakeStore(), timers)  # type: ignore[arg-type]
    for index, category in enumerate(CATEGORIES):
        await service.handle(envelope(f"category-{index}", "press", {"category": category}))
    assert timers.press_calls == list(CATEGORIES)


@pytest.mark.asyncio
async def test_backfill_supports_prompt_retry_and_one_line_fast_path():
    service = GryphonCommandService(FakeStore(), FakeTimers())  # type: ignore[arg-type]

    prompt = await service.handle(envelope("backfill-1", "backfill"))
    assert prompt["actions"][0]["expectInput"] == {
        "command": "backfill_minutes",
        "expiresInSeconds": 300,
    }

    invalid = await service.handle(
        envelope("backfill-2", "backfill_minutes", {"text": "many"})
    )
    assert invalid["actions"][0]["expectInput"]["command"] == "backfill_minutes"
    assert "whole number" in invalid["actions"][0]["text"]

    valid = await service.handle(
        envelope("backfill-3", "backfill_minutes", {"text": "30"})
    )
    buttons = [button for row in valid["actions"][0]["buttons"] for button in row]
    assert all(button["command"] == "backfill_select" for button in buttons)
    assert all(button["arguments"]["minutes"] == 30 for button in buttons)

    fast_path = await service.handle(
        envelope("backfill-4", "backfill", {"text": "45"})
    )
    fast_buttons = [button for row in fast_path["actions"][0]["buttons"] for button in row]
    assert all(button["arguments"]["minutes"] == 45 for button in fast_buttons)


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
        if route.endswith("command-catalog"):
            return {
                "schema": "exocortex.telegram.command-catalog.v1",
                "serviceId": "chronos",
                "commands": list(CHRONOS_COMMAND_CATALOG),
            }
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
        (
            "PUT",
            "/v1/service/command-catalog",
            {
                "schema": "exocortex.telegram.command-catalog.v1",
                "commands": list(CHRONOS_COMMAND_CATALOG),
            },
        ),
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
async def test_command_catalog_retries_without_blocking_startup(monkeypatch):
    client = GryphonClient("/run/gryphon/client.sock", Path("unused.token"), 1)
    status_calls = 0
    sync_calls = 0

    async def status():
        nonlocal status_calls
        status_calls += 1
        if status_calls == 1:
            raise GryphonError("temporarily unavailable", 503)
        return {"connected": True}

    async def sync():
        nonlocal sync_calls
        sync_calls += 1
        return {"commands": []}

    async def sleep(_: float):
        if sync_calls:
            raise asyncio.CancelledError

    monkeypatch.setattr(client, "status", status)
    monkeypatch.setattr(client, "sync_command_catalog", sync)
    monkeypatch.setattr(asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await client.maintain_command_catalog(retry_seconds=0)
    assert status_calls == 2
    assert sync_calls == 1


def test_command_catalog_comparison_ignores_gryphon_sort_order():
    assert GryphonClient._command_catalog_is_current({
        "commands": list(reversed(CHRONOS_COMMAND_CATALOG)),
    }) is True


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
