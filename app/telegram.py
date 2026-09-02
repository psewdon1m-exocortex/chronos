from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from .constants import CATEGORIES, CATEGORY_LABELS
from .runtime import RuntimeState
from .store import Store
from .timer_service import TimerError, TimerService, timezone_for


LOGGER = logging.getLogger("chronos.telegram")
MAX_BACKFILL_MINUTES = 10080


class BackfillFlow(StatesGroup):
    minutes = State()
    category = State()


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


def keyboard() -> ReplyKeyboardMarkup:
    buttons = [KeyboardButton(text=CATEGORY_LABELS[key]) for key in CATEGORIES]
    return ReplyKeyboardMarkup(
        keyboard=[buttons[:2], buttons[2:]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Select the current category",
    )


def category_choice_keyboard(action: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=CATEGORY_LABELS[key],
            callback_data=f"chronos:{action}:{key}",
        )
        for key in CATEGORIES
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])


class TelegramSupervisor:
    def __init__(self, runtime: RuntimeState, store: Store, timers: TimerService) -> None:
        self.runtime = runtime
        self.store = store
        self.timers = timers
        self._stop = asyncio.Event()
        self._bot: Bot | None = None
        self._polling: asyncio.Task[None] | None = None
        self._auxiliary: asyncio.Task[None] | None = None
        self._state: dict[str, Any] = {
            "configured": False,
            "running": False,
            "username": None,
            "last_error": None,
        }

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._state)

    async def stop(self) -> None:
        self._stop.set()
        self.runtime.changed.set()
        await self._stop_bot()

    async def _stop_bot(self) -> None:
        if self._polling:
            self._polling.cancel()
            with suppress(asyncio.CancelledError):
                await self._polling
            self._polling = None
        if self._auxiliary:
            self._auxiliary.cancel()
            with suppress(asyncio.CancelledError):
                await self._auxiliary
            self._auxiliary = None
        if self._bot:
            await self._bot.session.close()
            self._bot = None
        self._state["running"] = False

    async def run(self) -> None:
        active_token = ""
        while not self._stop.is_set():
            token = self.runtime.config.telegram_token
            self._state["configured"] = bool(token)
            if token != active_token:
                await self._stop_bot()
                active_token = token
                if token:
                    await self._start_bot(token)
            self.runtime.clear_change()
            change_task = asyncio.create_task(self.runtime.changed.wait())
            stop_task = asyncio.create_task(self._stop.wait())
            done, pending = await asyncio.wait(
                {change_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                with suppress(asyncio.CancelledError):
                    await task

    async def _start_bot(self, token: str) -> None:
        try:
            bot = Bot(token=token)
            identity = await bot.get_me()
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Open Chronos controls"),
                    BotCommand(command="status", description="Show the active timer"),
                    BotCommand(command="stats", description="Show today's balance"),
                    BotCommand(command="week", description="Show this week's balance"),
                    BotCommand(command="month", description="Show this month's balance"),
                    BotCommand(command="stop", description="Stop the active timer"),
                    BotCommand(command="undo", description="Undo the last timer action"),
                    BotCommand(command="retype", description="Change the last completed session"),
                    BotCommand(command="backfill", description="Insert a completed past session"),
                    BotCommand(command="link", description="Link this Telegram account"),
                ]
            )
            dispatcher = Dispatcher()
            dispatcher.include_router(self._router())
            dispatcher["store"] = self.store
            dispatcher["timers"] = self.timers
            self._bot = bot
            self._state.update(
                {
                    "running": True,
                    "username": identity.username,
                    "last_error": None,
                }
            )
            self._polling = asyncio.create_task(
                dispatcher.start_polling(bot, handle_signals=False),
                name="chronos-telegram-polling",
            )
            self._polling.add_done_callback(self._polling_finished)
            self._auxiliary = asyncio.create_task(
                self._notification_loop(bot), name="chronos-telegram-notifications"
            )
        except Exception as error:
            LOGGER.exception("Telegram bot startup failed")
            self._state.update({"running": False, "last_error": str(error)})
            if self._bot:
                await self._bot.session.close()
                self._bot = None

    def _polling_finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error:
            LOGGER.error("Telegram polling stopped: %s", error)
            self._state.update({"running": False, "last_error": str(error)})

    async def _authorized(self, message: Message) -> bool:
        if message.from_user and await self.store.is_telegram_owner(message.from_user.id):
            return True
        await message.answer(
            "This is a private Chronos instance. Link your account from the web interface first."
        )
        return False

    async def _authorized_callback(self, callback: CallbackQuery) -> bool:
        if await self.store.is_telegram_owner(callback.from_user.id):
            return True
        await callback.answer("This is a private Chronos instance.", show_alert=True)
        return False

    async def _period_message(self, start: datetime, end: datetime, title: str) -> str:
        data = await self.timers.analytics(start, end)
        if not data["total_seconds"]:
            return f"{title}\nNo tracked time yet."
        lines = [title, f"Total: {format_duration(data['total_seconds'])}"]
        for item in data["categories"]:
            lines.append(
                f"{item['label']}: {item['percent']:.2f}% ({format_duration(item['seconds'])})"
            )
        return "\n".join(lines)

    def _router(self) -> Router:
        router = Router()

        @router.message(Command("link"))
        async def link(message: Message, store: Store) -> None:
            if not message.from_user:
                return
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) != 2:
                await message.answer("Use /link followed by the one-time code shown in Chronos.")
                return
            if await store.telegram_owner_id():
                if await store.is_telegram_owner(message.from_user.id):
                    await message.answer("This Telegram account is already linked.", reply_markup=keyboard())
                else:
                    await message.answer("This private Chronos instance is already linked.")
                return
            if not await store.consume_link_code(parts[1].strip(), message.from_user.id):
                await message.answer("The link code is invalid or has expired.")
                return
            await store.audit(
                status="success",
                action="telegram.linked",
                target=str(message.from_user.id),
                actor="telegram",
                message="Telegram owner linked",
            )
            await message.answer("Telegram linked to Chronos.", reply_markup=keyboard())

        @router.message(Command("start"))
        async def start(message: Message) -> None:
            if not await self._authorized(message):
                return
            await message.answer(
                "Chronos is ready. Select a category to start or switch the timer.",
                reply_markup=keyboard(),
            )

        @router.message(Command("status"))
        async def status(message: Message, timers: TimerService) -> None:
            if not await self._authorized(message):
                return
            active = await timers.active()
            if not active:
                await message.answer("No timer is active.", reply_markup=keyboard())
                return
            await message.answer(
                f"Active: {active['label']}\nElapsed: "
                f"{format_duration(active['timer_elapsed_seconds'])}",
                reply_markup=keyboard(),
            )

        async def show_period(message: Message, period: str) -> None:
            if not await self._authorized(message):
                return
            settings = await self.store.settings()
            zone = timezone_for(str(settings["timezone"]))
            now = datetime.now(zone)
            if period == "today":
                start_date = now.date()
                title = "Today"
            elif period == "week":
                week_start = int(settings["week_starts_on"])
                offset = (now.isoweekday() - week_start) % 7
                start_date = now.date() - timedelta(days=offset)
                title = "This week"
            else:
                start_date = now.date().replace(day=1)
                title = "This month"
            start = datetime.combine(start_date, time.min, tzinfo=zone)
            end = now
            await message.answer(await self._period_message(start, end, title))

        @router.message(Command("stats"))
        async def stats(message: Message) -> None:
            await show_period(message, "today")

        @router.message(Command("week"))
        async def week(message: Message) -> None:
            await show_period(message, "week")

        @router.message(Command("month"))
        async def month(message: Message) -> None:
            await show_period(message, "month")

        @router.message(Command("stop"))
        async def stop(message: Message, timers: TimerService) -> None:
            if not await self._authorized(message):
                return
            stopped = await timers.stop(actor="telegram")
            if not stopped:
                await message.answer("No timer is active.")
                return
            await message.answer(
                f"Stopped {stopped['public_id']} ({stopped['label']}). Duration: "
                f"{format_duration(stopped['timer_elapsed_seconds'])}."
            )

        @router.message(Command("undo"))
        async def undo(message: Message, timers: TimerService) -> None:
            if not await self._authorized(message):
                return
            try:
                result = await timers.undo(actor="telegram")
            except TimerError as error:
                await message.answer(str(error))
                return
            await message.answer(f"Undone: {result['undone']}.", reply_markup=keyboard())

        @router.message(Command("retype"))
        async def retype(message: Message, timers: TimerService, state: FSMContext) -> None:
            if not await self._authorized(message):
                return
            await state.clear()
            latest = await timers.last_completed()
            if latest is None:
                await message.answer("There is no completed session to change.")
                return
            await message.answer(
                f"Choose a new category for {latest['public_id']} ({latest['label']}).",
                reply_markup=category_choice_keyboard(
                    f"retype:{latest['public_id']}"
                ),
            )

        @router.callback_query(F.data.startswith("chronos:retype:"))
        async def retype_choice(callback: CallbackQuery, timers: TimerService) -> None:
            if not await self._authorized_callback(callback):
                return
            parts = (callback.data or "").split(":")
            if len(parts) != 4:
                await callback.answer("This category choice has expired.", show_alert=True)
                return
            public_id, category = parts[2], parts[3]
            try:
                changed = await timers.retype_last_completed(
                    category,
                    actor="telegram",
                    expected_public_id=public_id,
                )
            except (TimerError, ValueError) as error:
                await callback.answer(str(error), show_alert=True)
                return
            await callback.answer("Category changed.")
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(
                    f"{changed['public_id']} is now {changed['label']}.",
                    reply_markup=keyboard(),
                )

        @router.message(Command("backfill"))
        async def backfill(message: Message, state: FSMContext) -> None:
            if not await self._authorized(message):
                return
            await state.clear()
            await state.set_state(BackfillFlow.minutes)
            await message.answer(
                "How many recent minutes should become a completed session? "
                "Send a whole number."
            )

        @router.message(BackfillFlow.minutes)
        async def backfill_minutes(message: Message, state: FSMContext) -> None:
            if not await self._authorized(message):
                await state.clear()
                return
            raw = (message.text or "").strip()
            try:
                minutes = int(raw)
            except ValueError:
                await message.answer("Send the number of minutes as a whole number.")
                return
            if minutes < 1 or minutes > MAX_BACKFILL_MINUTES:
                await message.answer(
                    f"Minutes must be between 1 and {MAX_BACKFILL_MINUTES}."
                )
                return
            await state.update_data(minutes=minutes)
            await state.set_state(BackfillFlow.category)
            await message.answer(
                f"Choose the category for the completed {minutes}-minute session.",
                reply_markup=category_choice_keyboard("backfill"),
            )

        @router.callback_query(
            BackfillFlow.category,
            F.data.startswith("chronos:backfill:"),
        )
        async def backfill_category(
            callback: CallbackQuery, timers: TimerService, state: FSMContext
        ) -> None:
            if not await self._authorized_callback(callback):
                await state.clear()
                return
            data = await state.get_data()
            minutes = int(data.get("minutes", 0))
            category = (callback.data or "").rsplit(":", 1)[-1]
            try:
                result = await timers.backfill_completed(
                    category,
                    minutes,
                    actor="telegram",
                    source="telegram",
                )
            except (TimerError, ValueError) as error:
                await callback.answer(str(error), show_alert=True)
                return
            await state.clear()
            await callback.answer("Past session inserted.")
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
                created = result["created"]
                affected = len(result["trimmed_ids"]) + len(result["deleted_ids"])
                active = result["active"]
                active_text = (
                    f" Active {active['label']} continues at "
                    f"{format_duration(active['timer_elapsed_seconds'])}."
                    if active
                    else " No timer is active."
                )
                await callback.message.answer(
                    f"Created {created['public_id']} ({created['label']}) for the "
                    f"last {minutes} minutes. Adjusted {affected} existing session(s)."
                    f"{active_text}",
                    reply_markup=keyboard(),
                )

        @router.message(F.text)
        async def category_button(message: Message, timers: TimerService) -> None:
            if not await self._authorized(message):
                return
            category = next(
                (
                    key
                    for key, label in CATEGORY_LABELS.items()
                    if (message.text or "").strip().lower() == label.lower()
                ),
                None,
            )
            if category is None:
                await message.answer("Use the Chronos buttons or a bot command.")
                return
            result = await timers.press(category, actor="telegram", source="telegram")
            if result["action"] == "timer.restarted":
                await message.answer(
                    f"Restarted {result['started']['public_id']} "
                    f"({result['started']['label']}). Previous: "
                    f"{result['stopped']['public_id']} / "
                    f"{format_duration(result['stopped']['timer_elapsed_seconds'])}."
                )
            elif result["started"] and result["stopped"]:
                await message.answer(
                    f"Switched to {result['started']['label']}. Previous: "
                    f"{result['stopped']['public_id']} / "
                    f"{format_duration(result['stopped']['timer_elapsed_seconds'])}."
                )
            elif result["started"]:
                await message.answer(
                    f"Started {result['started']['public_id']} "
                    f"({result['started']['label']})."
                )
            else:
                await message.answer(
                    f"Stopped {result['stopped']['public_id']} "
                    f"({result['stopped']['label']}). Duration: "
                    f"{format_duration(result['stopped']['timer_elapsed_seconds'])}."
                )

        return router

    async def _notification_loop(self, bot: Bot) -> None:
        reminded_session: int | None = None
        summarized_date: date | None = None
        while True:
            await asyncio.sleep(30)
            owner_id = await self.store.telegram_owner_id()
            if owner_id is None:
                continue
            settings = await self.store.settings()
            active = await self.timers.active()
            reminder_minutes = int(settings.get("reminder_minutes", 0))
            if (
                active
                and reminder_minutes > 0
                and active["timer_elapsed_seconds"] >= reminder_minutes * 60
                and reminded_session != active["id"]
            ):
                await bot.send_message(
                    owner_id,
                    f"{active['label']} has been active for "
                    f"{format_duration(active['timer_elapsed_seconds'])}. "
                    "Use /status or /stop.",
                )
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
            start = datetime.combine(now.date(), time.min, tzinfo=zone)
            await bot.send_message(
                owner_id,
                await self._period_message(start, now, "Daily summary"),
            )
            summarized_date = now.date()
