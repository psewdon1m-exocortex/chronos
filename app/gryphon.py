from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import http.client
import json
from pathlib import Path
import re
import socket
from typing import Any

from .constants import CATEGORIES, CATEGORY_LABELS
from .store import Store
from .timer_service import TimerError, TimerService, timezone_for


_USER_ID = re.compile(r"^[1-9]\d{0,18}$")
_CHAT_ID = re.compile(r"^-?[1-9]\d{0,18}$")
_COMMAND = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class GryphonError(RuntimeError):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(self.socket_path)
        self.sock = connection


class GryphonClient:
    def __init__(self, socket_path: str, token_file: Path, timeout_seconds: float) -> None:
        self.socket_path = socket_path
        self.token_file = token_file
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, route: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token_file.is_file():
            raise GryphonError("Gryphon service token is not configured", 503)
        token = self.token_file.read_text(encoding="utf-8").strip()
        if len(token) < 24:
            raise GryphonError("Gryphon service token is invalid", 503)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Host": "gryphon.local",
        }
        if payload is not None:
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(payload))})
        connection = _UnixHTTPConnection(self.socket_path, self.timeout_seconds)
        try:
            connection.request(method, route, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise GryphonError("Gryphon response exceeds 1 MB")
            try:
                result = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise GryphonError("Gryphon returned invalid JSON") from error
            if not isinstance(result, dict):
                raise GryphonError("Gryphon returned an invalid response")
            if not 200 <= response.status < 300:
                status = 409 if response.status == 409 else 401 if response.status == 401 else 502
                raise GryphonError(str(result.get("error") or f"Gryphon returned HTTP {response.status}"), status)
            return result
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as error:
            raise GryphonError("Gryphon is not installed or is unavailable on this VPS", 503) from error
        except (OSError, http.client.HTTPException) as error:
            raise GryphonError(f"Gryphon request failed: {error}") from error
        finally:
            connection.close()

    async def status(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "GET", "/v1/service")
        if (
            result.get("schema") != "exocortex.gryphon.service-status.v1"
            or result.get("serviceId") != "chronos"
            or not isinstance(result.get("version"), str)
            or not isinstance(result.get("connected"), bool)
            or (result.get("bot") is not None and not isinstance(result.get("bot"), dict))
            or (result.get("binding") is not None and not isinstance(result.get("binding"), dict))
        ):
            raise GryphonError("Gryphon returned an invalid service status")
        return result

    async def bots(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "GET", "/v1/service/bots")
        if (
            result.get("schema") != "exocortex.gryphon.service-bots.v1"
            or result.get("serviceId") != "chronos"
            or not isinstance(result.get("bots"), list)
            or any(
                not isinstance(bot, dict)
                or not isinstance(bot.get("id"), str)
                or not isinstance(bot.get("alias"), str)
                or not isinstance(bot.get("state"), str)
                for bot in result["bots"]
            )
        ):
            raise GryphonError("Gryphon returned an invalid bot list")
        return result

    async def connect(self, bot_id: str, adapter_url: str) -> dict[str, Any]:
        if not bot_id or len(bot_id) > 200:
            raise GryphonError("Gryphon bot ID is invalid", 400)
        return await asyncio.to_thread(
            self._request,
            "PUT",
            "/v1/service/connection",
            {
                "botId": bot_id,
                "commandPrefix": "chronos",
                "adapterUrl": adapter_url,
            },
        )

    async def disconnect(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "DELETE", "/v1/service/connection")

    async def issue_link_challenge(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "POST", "/v1/service/link-challenges")
        if not all(isinstance(result.get(key), str) for key in ("code", "expiresAt", "command")):
            raise GryphonError("Gryphon returned an invalid link challenge")
        return result

    async def notify(self, text: str, idempotency_key: str) -> None:
        await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/service/notifications",
            {"text": text, "idempotencyKey": idempotency_key},
        )


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _message(
    text: str, buttons: list[list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    action: dict[str, Any] = {"type": "send_message", "text": text}
    if buttons:
        action["buttons"] = buttons
    return {"schema": "exocortex.telegram.response.v1", "actions": [action]}


def _category_buttons(command: str, extra: dict[str, Any] | None = None):
    buttons = [
        {
            "text": CATEGORY_LABELS[category],
            "command": command,
            "arguments": {"category": category, **(extra or {})},
        }
        for category in CATEGORIES
    ]
    return [buttons[:2], buttons[2:]]


class GryphonCommandService:
    def __init__(self, store: Store, timers: TimerService) -> None:
        self.store = store
        self.timers = timers

    async def handle(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if envelope.get("schema") != "exocortex.telegram.command.v1":
            raise ValueError("Unsupported Gryphon command schema")
        if envelope.get("serviceId") != "chronos":
            raise ValueError("Gryphon command targets another service")
        event_id = str(envelope.get("eventId") or "")
        if not event_id or len(event_id) > 200:
            raise ValueError("Gryphon event ID is invalid")
        actor = envelope.get("actor")
        if not isinstance(actor, dict) or actor.get("chatType") != "private":
            raise ValueError("Gryphon command requires a private chat")
        if not _USER_ID.fullmatch(str(actor.get("telegramUserId") or "")):
            raise ValueError("Gryphon user ID is invalid")
        if not _CHAT_ID.fullmatch(str(actor.get("chatId") or "")):
            raise ValueError("Gryphon chat ID is invalid")
        cached = await self.store.begin_gryphon_event(event_id)
        if cached is not None:
            return cached
        command = str(envelope.get("command") or "")
        if not _COMMAND.fullmatch(command):
            raise ValueError("Gryphon command is invalid")
        arguments = envelope.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            result = await self._execute(command, arguments)
            await self.store.complete_gryphon_event(event_id, result)
            return result
        except (TimerError, ValueError) as error:
            result = _message(str(error))
            await self.store.complete_gryphon_event(event_id, result)
            return result
        except Exception:
            await self.store.fail_gryphon_event(event_id)
            raise

    async def _execute(
        self, command: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        if command in {"start", "menu"}:
            return _message(
                "Chronos is ready. Select a category to start or switch the timer.",
                _category_buttons("press"),
            )
        if command == "press":
            category = str(arguments.get("category") or "")
            result = await self.timers.press(
                category, actor="telegram", source="telegram"
            )
            return _message(self._press_message(result))
        if command == "status":
            active = await self.timers.active()
            if not active:
                return _message("No timer is active.")
            return _message(
                f"Active: {active['label']}\nElapsed: "
                f"{format_duration(active['timer_elapsed_seconds'])}"
            )
        if command in {"stats", "week", "month"}:
            return _message(await self.period_message(command))
        if command == "stop":
            stopped = await self.timers.stop(actor="telegram")
            if not stopped:
                return _message("No timer is active.")
            return _message(
                f"Stopped {stopped['public_id']} ({stopped['label']}). Duration: "
                f"{format_duration(stopped['timer_elapsed_seconds'])}."
            )
        if command == "undo":
            result = await self.timers.undo(actor="telegram")
            return _message(f"Undone: {result['undone']}.")
        if command == "binding_revoked":
            return _message("Chronos binding revoked.")
        if command == "retype":
            latest = await self.timers.last_completed()
            if latest is None:
                return _message("There is no completed session to change.")
            return _message(
                f"Choose a new category for {latest['public_id']} ({latest['label']}).",
                _category_buttons(
                    "retype_select", {"public_id": latest["public_id"]}
                ),
            )
        if command == "retype_select":
            changed = await self.timers.retype_last_completed(
                str(arguments.get("category") or ""),
                actor="telegram",
                expected_public_id=str(arguments.get("public_id") or ""),
            )
            return _message(
                f"{changed['public_id']} is now {changed['label']}."
            )
        if command == "backfill":
            raw = str(arguments.get("text") or "").strip()
            try:
                minutes = int(raw)
            except ValueError as error:
                raise ValueError("Use /chronos backfill MINUTES.") from error
            if minutes < 1 or minutes > 10080:
                raise ValueError("Minutes must be between 1 and 10080.")
            return _message(
                f"Choose the category for the completed {minutes}-minute session.",
                _category_buttons("backfill_select", {"minutes": minutes}),
            )
        if command == "backfill_select":
            minutes = int(arguments.get("minutes") or 0)
            result = await self.timers.backfill_completed(
                str(arguments.get("category") or ""),
                minutes,
                actor="telegram",
                source="telegram",
            )
            created = result["created"]
            affected = len(result["trimmed_ids"]) + len(result["deleted_ids"])
            active = result["active"]
            active_text = (
                f" Active {active['label']} continues at "
                f"{format_duration(active['timer_elapsed_seconds'])}."
                if active
                else " No timer is active."
            )
            return _message(
                f"Created {created['public_id']} ({created['label']}) for the "
                f"last {minutes} minutes. Adjusted {affected} existing session(s)."
                f"{active_text}"
            )
        return _message(
            "Chronos commands: status, stats, week, month, stop, undo, "
            "retype, backfill MINUTES."
        )

    async def period_message(self, period: str) -> str:
        settings = await self.store.settings()
        zone = timezone_for(str(settings["timezone"]))
        now = datetime.now(zone)
        if period == "stats":
            start_date = now.date()
            title = "Today"
        elif period == "week":
            week_start = int(settings["week_starts_on"])
            start_date = now.date() - timedelta(
                days=(now.isoweekday() - week_start) % 7
            )
            title = "This week"
        else:
            start_date = now.date().replace(day=1)
            title = "This month"
        data = await self.timers.analytics(
            datetime.combine(start_date, time.min, tzinfo=zone), now
        )
        if not data["total_seconds"]:
            return f"{title}\nNo tracked time yet."
        lines = [title, f"Total: {format_duration(data['total_seconds'])}"]
        for item in data["categories"]:
            lines.append(
                f"{item['label']}: {item['percent']:.2f}% "
                f"({format_duration(item['seconds'])})"
            )
        return "\n".join(lines)

    @staticmethod
    def _press_message(result: dict[str, Any]) -> str:
        if result["action"] == "timer.restarted":
            return (
                f"Restarted {result['started']['public_id']} "
                f"({result['started']['label']}). Previous: "
                f"{result['stopped']['public_id']} / "
                f"{format_duration(result['stopped']['timer_elapsed_seconds'])}."
            )
        if result["started"] and result["stopped"]:
            return (
                f"Switched to {result['started']['label']}. Previous: "
                f"{result['stopped']['public_id']} / "
                f"{format_duration(result['stopped']['timer_elapsed_seconds'])}."
            )
        if result["started"]:
            return (
                f"Started {result['started']['public_id']} "
                f"({result['started']['label']})."
            )
        return (
            f"Stopped {result['stopped']['public_id']} "
            f"({result['stopped']['label']}). Duration: "
            f"{format_duration(result['stopped']['timer_elapsed_seconds'])}."
        )


class GryphonNotifier:
    def __init__(self, client: GryphonClient) -> None:
        self.client = client

    async def send(self, text: str, idempotency_key: str) -> None:
        await self.client.notify(text, idempotency_key)


class ChronosNotificationSupervisor:
    def __init__(
        self,
        store: Store,
        timers: TimerService,
        commands: GryphonCommandService,
        notifier: GryphonNotifier,
    ) -> None:
        self.store = store
        self.timers = timers
        self.commands = commands
        self.notifier = notifier
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        reminded_session: int | None = None
        summarized_date: date | None = None
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
                continue
            except TimeoutError:
                pass
            settings = await self.store.settings()
            active = await self.timers.active()
            reminder_minutes = int(settings.get("reminder_minutes", 0))
            if (
                active
                and reminder_minutes > 0
                and active["timer_elapsed_seconds"] >= reminder_minutes * 60
                and reminded_session != active["id"]
            ):
                try:
                    await self.notifier.send(
                        f"{active['label']} has been active for "
                        f"{format_duration(active['timer_elapsed_seconds'])}. "
                        "Open /chronos for controls.",
                        f"timer-reminder:{active['id']}",
                    )
                except Exception:
                    continue
                reminded_session = active["id"]
            if not active:
                reminded_session = None
            if not settings.get("daily_summary_enabled"):
                continue
            zone = timezone_for(str(settings["timezone"]))
            now = datetime.now(zone)
            summary_time = str(settings.get("daily_summary_time", "21:00"))
            if now.strftime("%H:%M") != summary_time or summarized_date == now.date():
                continue
            try:
                await self.notifier.send(
                    await self.commands.period_message("stats"),
                    f"daily-summary:{now.date().isoformat()}",
                )
            except Exception:
                continue
            summarized_date = now.date()
