from __future__ import annotations

import asyncio
import csv
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta, timezone
import hmac
from io import BytesIO, StringIO
import json
import logging
from pathlib import Path
import re
import secrets
import time as time_module
from typing import Any, AsyncIterator
from urllib.parse import urlparse
import zipfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import RuntimeConfig, load_config, validate_runtime_config
from .constants import CATEGORIES, CATEGORY_LABELS, DEFAULT_SETTINGS
from .database import create_pool, run_migrations
from .kernel_register import KernelRegisterError, apply_register, load_snapshot
from .runtime import RuntimeState
from .security import (
    create_session_token,
    hash_password,
    new_csrf_token,
    new_link_code,
    validate_new_password,
    verify_password,
    verify_session_token,
)
from .store import Store
from .telegram import TelegramSupervisor
from .timer_service import TimerError, TimerService, timezone_for
from .updater import UpdaterClient, UpdaterError, check_github_release


LOGGER = logging.getLogger("chronos.api")
COOKIE_NAME = "chronos_session"
CSRF_COOKIE_NAME = "chronos_csrf"
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
LOGIN_ATTEMPTS: dict[str, list[float]] = {}


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class TimerInput(BaseModel):
    category: str


class SessionInput(BaseModel):
    category: str
    started_at: datetime
    stopped_at: datetime
    note: str = Field(default="", max_length=500)


class SessionUpdate(BaseModel):
    category: str
    started_at: datetime
    stopped_at: datetime | None
    note: str = Field(default="", max_length=500)


class SettingsInput(BaseModel):
    profile_name: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=128)
    week_starts_on: int = Field(ge=1, le=7)
    time_format: str
    date_format: str
    reminder_minutes: int = Field(ge=0, le=10080)
    daily_summary_enabled: bool
    daily_summary_time: str
    theme_dark: str
    theme_light: str
    theme_accent: str
    sidebar_auto_hide: bool


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class UpdateInput(BaseModel):
    version: str = Field(min_length=5, max_length=64)


def _request_id() -> str:
    return secrets.token_hex(12)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_login_rate(request: Request) -> None:
    key = _client_key(request)
    now = time_module.monotonic()
    attempts = [value for value in LOGIN_ATTEMPTS.get(key, []) if now - value < 300]
    if len(attempts) >= 10:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    attempts.append(now)
    LOGIN_ATTEMPTS[key] = attempts


def _clear_login_rate(request: Request) -> None:
    LOGIN_ATTEMPTS.pop(_client_key(request), None)


async def operator(request: Request) -> dict[str, Any]:
    store: Store = request.app.state.store
    runtime: RuntimeState = request.app.state.runtime
    security = await store.security()
    payload = verify_session_token(
        request.cookies.get(COOKIE_NAME),
        runtime.config.session_secret,
        int(security["session_generation"]),
    )
    if payload is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    request.state.operator = security["username"]
    request.state.session = payload
    return payload


async def mutation_operator(
    request: Request, session: dict[str, Any] = Depends(operator)
) -> dict[str, Any]:
    header = request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    expected = str(session.get("csrf") or "")
    if not header or not cookie or not hmac.compare_digest(header, expected) or not hmac.compare_digest(cookie, expected):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return session


def _set_session_cookies(
    response: Response,
    config: RuntimeConfig,
    token: str,
    csrf: str,
) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=12 * 60 * 60,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf,
        max_age=12 * 60 * 60,
        httponly=False,
        secure=config.cookie_secure,
        samesite="strict",
        path="/",
    )


def _clear_session_cookies(response: Response, config: RuntimeConfig) -> None:
    response.delete_cookie(
        COOKIE_NAME, secure=config.cookie_secure, httponly=True, samesite="strict", path="/"
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME, secure=config.cookie_secure, httponly=False, samesite="strict", path="/"
    )


def _validate_settings(data: SettingsInput) -> dict[str, Any]:
    try:
        if data.timezone != "UTC":
            ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(status_code=400, detail="Unknown timezone") from error
    if data.time_format not in {"12h", "24h"}:
        raise HTTPException(status_code=400, detail="Unsupported time format")
    if data.date_format not in {"DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"}:
        raise HTTPException(status_code=400, detail="Unsupported date format")
    if not TIME_PATTERN.fullmatch(data.daily_summary_time):
        raise HTTPException(status_code=400, detail="Daily summary time must use HH:MM")
    for name, value in {
        "theme_dark": data.theme_dark,
        "theme_light": data.theme_light,
        "theme_accent": data.theme_accent,
    }.items():
        if not COLOR_PATTERN.fullmatch(value):
            raise HTTPException(status_code=400, detail=f"Invalid {name} color")
    return data.model_dump()


def _backup_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _backup_zip(value: dict[str, Any], version: str) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("chronos-backup.json", _backup_json(value))
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema": "exocortex.chronos.backup-manifest.v1",
                    "service": "chronos",
                    "version": version,
                    "created_at": value["created_at"],
                    "entries": ["chronos-backup.json"],
                },
                indent=2,
            )
            + "\n",
        )
        archive.writestr(
            "README.txt",
            "Chronos logical backup. Restore this ZIP from Settings / Backup.\n",
        )
    return output.getvalue()


async def _load_register_once(app: FastAPI) -> None:
    runtime: RuntimeState = app.state.runtime
    store: Store = app.state.store
    previous = runtime.config.register_revision
    try:
        snapshot = await asyncio.to_thread(load_snapshot, runtime.config)
        updated = apply_register(runtime.config, snapshot)
        await runtime.replace(updated)
        if updated.register_revision and updated.register_revision != previous:
            await store.audit(
                status="info",
                action="kernel.register.refreshed",
                target=updated.register_revision,
                actor="system",
                message="Kernel Register configuration applied",
            )
    except KernelRegisterError as error:
        LOGGER.warning("Kernel Register refresh failed: %s", error)
        await store.audit(
            status="error",
            action="kernel.register.refresh_failed",
            actor="system",
            message=str(error),
        )


async def _register_refresh_loop(app: FastAPI) -> None:
    while True:
        await _load_register_once(app)
        await asyncio.sleep(app.state.runtime.config.kernel_refresh_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = load_config()
    validate_runtime_config(config)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    pool = await create_pool(config.database_url)
    migrations_dir = Path(__file__).resolve().parents[1] / "infrastructure" / "migrations"
    await run_migrations(pool, migrations_dir)
    store = Store(
        pool,
        audit_max_entries=config.audit_max_entries,
        audit_retention_days=config.audit_retention_days,
    )
    await store.initialize(
        admin_username=config.admin_username,
        admin_password=config.admin_password,
        default_timezone=config.default_timezone,
    )
    runtime = RuntimeState(config)
    timers = TimerService(store)
    telegram = TelegramSupervisor(runtime, store, timers)
    app.state.pool = pool
    app.state.store = store
    app.state.runtime = runtime
    app.state.timers = timers
    app.state.telegram = telegram
    app.state.updater = UpdaterClient(
        config.updater_socket_path, config.updater_control_token, config.updater_head_id
    )
    await _load_register_once(app)
    register_task = asyncio.create_task(_register_refresh_loop(app), name="kernel-register-refresh")
    telegram_task = asyncio.create_task(telegram.run(), name="telegram-supervisor")
    try:
        yield
    finally:
        register_task.cancel()
        await telegram.stop()
        telegram_task.cancel()
        for task in (register_task, telegram_task):
            with suppress(asyncio.CancelledError):
                await task
        await pool.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Chronos",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or _request_id()
        started = time_module.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception("Unhandled request error", extra={"request_id": request.state.request_id})
            raise
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        response.headers["Server-Timing"] = f"app;dur={(time_module.monotonic() - started) * 1000:.1f}"
        return response

    @app.exception_handler(TimerError)
    async def timer_error(_: Request, error: TimerError):
        return JSONResponse(status_code=error.status, content={"error": str(error)})

    @app.exception_handler(UpdaterError)
    async def updater_error(_: Request, error: UpdaterError):
        return JSONResponse(status_code=error.status, content={"error": str(error)})

    @app.get("/api/health")
    async def health(request: Request):
        runtime: RuntimeState = request.app.state.runtime
        telegram: TelegramSupervisor = request.app.state.telegram
        try:
            await request.app.state.pool.fetchval("select 1")
            database = "available"
        except Exception:
            database = "unavailable"
        status = "available" if database == "available" else "unavailable"
        return {
            "status": status,
            "service": "chronos",
            "version": runtime.config.version,
            "database": database,
            "telegram": telegram.status,
            "register_revision": runtime.config.register_revision or None,
        }

    @app.get("/api/public/theme")
    async def public_theme(request: Request):
        settings = await request.app.state.store.settings()
        return {
            "dark": settings["theme_dark"],
            "light": settings["theme_light"],
            "accent": settings["theme_accent"],
        }

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        try:
            await operator(request)
        except HTTPException:
            return {"authenticated": False}
        security = await request.app.state.store.security()
        return {"authenticated": True, "username": security["username"]}

    @app.post("/api/auth/login")
    async def login(request: Request, body: LoginInput):
        _check_login_rate(request)
        store: Store = request.app.state.store
        runtime: RuntimeState = request.app.state.runtime
        security = await store.security()
        valid = hmac.compare_digest(body.username, str(security["username"])) and verify_password(
            body.password, str(security["password_hash"])
        )
        if not valid:
            await store.audit(
                status="denied",
                action="auth.login",
                target=body.username,
                actor="anonymous",
                message="Invalid operator credentials",
                request_id=request.state.request_id,
            )
            raise HTTPException(status_code=401, detail="Invalid login or password")
        _clear_login_rate(request)
        csrf = new_csrf_token()
        token = create_session_token(
            runtime.config.session_secret, int(security["session_generation"]), csrf
        )
        response = JSONResponse({"authenticated": True, "username": security["username"]})
        _set_session_cookies(response, runtime.config, token, csrf)
        await store.audit(
            status="success",
            action="auth.login",
            target=str(security["username"]),
            actor="operator",
            message="Operator signed in",
            request_id=request.state.request_id,
        )
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request, _: dict[str, Any] = Depends(mutation_operator)):
        response = JSONResponse({"authenticated": False})
        _clear_session_cookies(response, request.app.state.runtime.config)
        await request.app.state.store.audit(
            status="success",
            action="auth.logout",
            actor="operator",
            message="Operator signed out",
            request_id=request.state.request_id,
        )
        return response

    @app.get("/api/dashboard")
    async def dashboard(request: Request, _: dict[str, Any] = Depends(operator)):
        store: Store = request.app.state.store
        timers: TimerService = request.app.state.timers
        settings = await store.settings()
        zone = timezone_for(str(settings["timezone"]))
        now = datetime.now(zone)
        start = datetime.combine(now.date(), time.min, tzinfo=zone)
        analytics = await timers.analytics(start, now)
        recent = await timers.history(
            start=start,
            end=now + timedelta(seconds=1),
            category=None,
            query="",
            limit=6,
            offset=0,
        )
        active = await timers.active(now=now)
        return {
            "now": now.isoformat(),
            "profile_name": settings["profile_name"],
            "timezone": settings["timezone"],
            "categories": [
                {"key": key, "label": CATEGORY_LABELS[key]} for key in CATEGORIES
            ],
            "active": active,
            "today": analytics,
            "recent": recent["items"],
            "telegram": {
                **request.app.state.telegram.status,
                "linked": bool(await store.telegram_owner_id()),
            },
        }

    @app.post("/api/timer/press")
    async def timer_press(
        request: Request,
        body: TimerInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        return await request.app.state.timers.press(
            body.category, actor="operator", source="web"
        )

    @app.post("/api/timer/stop")
    async def timer_stop(request: Request, _: dict[str, Any] = Depends(mutation_operator)):
        result = await request.app.state.timers.stop(actor="operator")
        return {"stopped": result}

    @app.post("/api/actions/undo")
    async def undo(request: Request, _: dict[str, Any] = Depends(mutation_operator)):
        return await request.app.state.timers.undo(actor="operator")

    @app.get("/api/sessions")
    async def sessions(
        request: Request,
        start: datetime | None = None,
        end: datetime | None = None,
        category: str | None = None,
        q: str = "",
        limit: int = 100,
        offset: int = 0,
        _: dict[str, Any] = Depends(operator),
    ):
        return await request.app.state.timers.history(
            start=start,
            end=end,
            category=category,
            query=q,
            limit=limit,
            offset=offset,
        )

    @app.post("/api/sessions", status_code=201)
    async def create_session(
        request: Request,
        body: SessionInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        return await request.app.state.timers.create_manual(
            category=body.category,
            started_at=body.started_at,
            stopped_at=body.stopped_at,
            note=body.note,
            actor="operator",
        )

    @app.put("/api/sessions/{session_id}")
    async def update_session(
        request: Request,
        session_id: int,
        body: SessionUpdate,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        return await request.app.state.timers.update_session(
            session_id,
            category=body.category,
            started_at=body.started_at,
            stopped_at=body.stopped_at,
            note=body.note,
            actor="operator",
        )

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(
        request: Request,
        session_id: int,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        await request.app.state.timers.delete_session(session_id, actor="operator")
        return Response(status_code=204)

    @app.get("/api/analytics")
    async def analytics(
        request: Request,
        start: date,
        end: date,
        _: dict[str, Any] = Depends(operator),
    ):
        settings = await request.app.state.store.settings()
        period = await request.app.state.timers.period_for_dates(
            start, end, str(settings["timezone"])
        )
        return await request.app.state.timers.analytics(*period)

    @app.get("/api/export.csv")
    async def export_csv(request: Request, _: dict[str, Any] = Depends(operator)):
        rows = await request.app.state.store.sessions_for_export()
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "public_id",
                "category",
                "started_at",
                "stopped_at",
                "duration_seconds",
                "note",
                "source",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["public_id"],
                    row["category"],
                    row["started_at"].isoformat(),
                    row["stopped_at"].isoformat() if row["stopped_at"] else "",
                    row["duration_seconds"] or "",
                    row["note"],
                    row["source"],
                ]
            )
        filename = f"chronos-sessions-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.csv"
        return Response(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/settings")
    async def get_settings(request: Request, _: dict[str, Any] = Depends(operator)):
        runtime: RuntimeState = request.app.state.runtime
        return {
            "values": await request.app.state.store.settings(),
            "runtime": {
                "version": runtime.config.version,
                "public_url": runtime.config.public_url,
                "repository_url": runtime.config.repository_url,
                "register_revision": runtime.config.register_revision or None,
            },
            "telegram": {
                **request.app.state.telegram.status,
                "linked": bool(await request.app.state.store.telegram_owner_id()),
            },
        }

    @app.put("/api/settings")
    async def save_settings(
        request: Request,
        body: SettingsInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        values = await request.app.state.store.update_settings(_validate_settings(body))
        await request.app.state.store.audit(
            status="success",
            action="settings.updated",
            target="operator",
            actor="operator",
            message="Chronos personalization updated",
            request_id=request.state.request_id,
        )
        return {"values": values}

    @app.post("/api/settings/reset-appearance")
    async def reset_appearance(
        request: Request, _: dict[str, Any] = Depends(mutation_operator)
    ):
        values = await request.app.state.store.update_settings(
            {
                "theme_dark": DEFAULT_SETTINGS["theme_dark"],
                "theme_light": DEFAULT_SETTINGS["theme_light"],
                "theme_accent": DEFAULT_SETTINGS["theme_accent"],
            }
        )
        await request.app.state.store.audit(
            status="success",
            action="appearance.reset",
            target="theme",
            actor="operator",
            message="Appearance reset to defaults",
        )
        return {"values": values}

    @app.post("/api/security/password")
    async def change_password(
        request: Request,
        body: PasswordInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        store: Store = request.app.state.store
        security = await store.security()
        if not verify_password(body.current_password, str(security["password_hash"])):
            await store.audit(
                status="denied",
                action="security.password_change",
                actor="operator",
                message="Current password verification failed",
            )
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        try:
            validate_new_password(body.new_password)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        generation = await store.update_password(hash_password(body.new_password))
        csrf = new_csrf_token()
        token = create_session_token(
            request.app.state.runtime.config.session_secret, generation, csrf
        )
        response = JSONResponse({"changed": True})
        _set_session_cookies(response, request.app.state.runtime.config, token, csrf)
        await store.audit(
            status="success",
            action="security.password_change",
            target="operator",
            actor="operator",
            message="Operator password changed",
        )
        return response

    @app.post("/api/telegram/link-code")
    async def telegram_link_code(
        request: Request, _: dict[str, Any] = Depends(mutation_operator)
    ):
        if await request.app.state.store.telegram_owner_id():
            raise HTTPException(status_code=409, detail="Telegram is already linked")
        code = new_link_code()
        await request.app.state.store.create_link_code(code)
        await request.app.state.store.audit(
            status="info",
            action="telegram.link_code_created",
            target="owner",
            actor="operator",
            message="One-time Telegram link code created",
        )
        return {"code": code, "expires_in_seconds": 600}

    @app.delete("/api/telegram/link")
    async def telegram_unlink(
        request: Request, _: dict[str, Any] = Depends(mutation_operator)
    ):
        await request.app.state.store.unlink_telegram()
        await request.app.state.store.audit(
            status="success",
            action="telegram.unlinked",
            target="owner",
            actor="operator",
            message="Telegram account unlinked",
        )
        return {"linked": False}

    @app.get("/api/backup/export")
    async def export_backup(request: Request, _: dict[str, Any] = Depends(operator)):
        backup = await request.app.state.store.logical_backup()
        archive = _backup_zip(backup, request.app.state.runtime.config.version)
        filename = f"chronos-backup-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.zip"
        await request.app.state.store.audit(
            status="success",
            action="backup.exported",
            target=filename,
            actor="operator",
            message="Chronos backup prepared",
        )
        return Response(
            archive,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def parse_backup_upload(file: UploadFile) -> dict[str, Any]:
        body = await file.read(64 * 1024 * 1024 + 1)
        if len(body) > 64 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Backup exceeds 64 MB")
        try:
            if body.startswith(b"PK"):
                with zipfile.ZipFile(BytesIO(body)) as archive:
                    names = archive.namelist()
                    if "chronos-backup.json" not in names:
                        raise ValueError("Archive does not contain chronos-backup.json")
                    if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                        raise ValueError("Archive contains an unsafe path")
                    raw = archive.read("chronos-backup.json")
            else:
                raw = body
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
            raise HTTPException(status_code=400, detail=f"Invalid Chronos backup: {error}") from error

    @app.post("/api/backup/restore")
    async def restore_backup(
        request: Request,
        file: UploadFile = File(...),
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        backup = await parse_backup_upload(file)
        try:
            count = await request.app.state.store.restore_backup(backup)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await request.app.state.store.audit(
            status="success",
            action="backup.restored",
            target=file.filename or "backup",
            actor="operator",
            message=f"Restored {count} sessions",
        )
        return {"restored_sessions": count}

    @app.post("/api/internal/updater/restore")
    async def updater_restore(
        request: Request,
        file: UploadFile = File(...),
        x_updater_token: str = Header(default=""),
    ):
        expected = request.app.state.runtime.config.updater_control_token
        if not expected or not hmac.compare_digest(x_updater_token, expected):
            raise HTTPException(status_code=401, detail="Invalid Updater token")
        backup = await parse_backup_upload(file)
        try:
            count = await request.app.state.store.restore_backup(backup)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await request.app.state.store.audit(
            status="success",
            action="updater.backup_restored",
            target=file.filename or "backup",
            actor="updater",
            message=f"Updater restored {count} sessions",
        )
        return {"restored_sessions": count}

    @app.get("/api/logs")
    async def logs(
        request: Request, limit: int = 200, _: dict[str, Any] = Depends(operator)
    ):
        return {"events": await request.app.state.store.audit_events(limit)}

    @app.get("/api/logs/download")
    async def download_logs(request: Request, _: dict[str, Any] = Depends(operator)):
        events = await request.app.state.store.audit_events(10000)
        errors = [event for event in events if event["status"] in {"error", "denied"}]
        output = BytesIO()
        created = datetime.now(timezone.utc)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "events.jsonl",
                "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in reversed(events)),
            )
            archive.writestr("errors.json", json.dumps(errors, ensure_ascii=False, indent=2) + "\n")
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "schema": "exocortex.chronos.logs.v1",
                        "created_at": created.isoformat(),
                        "event_count": len(events),
                        "error_count": len(errors),
                    },
                    indent=2,
                )
                + "\n",
            )
            archive.writestr(
                "README.txt",
                "Chronos retained audit events. Secret values are never included.\n",
            )
        filename = f"chronos-logs-{created:%Y%m%d%H%M%S}.zip"
        return Response(
            output.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/updates/status")
    async def update_status(request: Request, _: dict[str, Any] = Depends(operator)):
        runtime: RuntimeState = request.app.state.runtime
        return {
            "service": "chronos",
            "installed_version": runtime.config.version,
            "repository_url": runtime.config.repository_url or None,
            "register_revision": runtime.config.register_revision or None,
            "updater": await request.app.state.updater.status(),
        }

    @app.post("/api/updates/check")
    async def update_check(
        request: Request, _: dict[str, Any] = Depends(mutation_operator)
    ):
        config = request.app.state.runtime.config
        if not config.repository_url:
            raise HTTPException(status_code=503, detail="Chronos repository is not configured")
        result = await check_github_release(
            config.repository_url, config.version, config.update_check_timeout_seconds
        )
        await request.app.state.store.audit(
            status="success",
            action="update.checked",
            target=result.get("available_version") or config.version,
            actor="operator",
            message="Chronos release check completed",
        )
        return result

    @app.post("/api/updates/apply")
    async def update_apply(
        request: Request,
        body: UpdateInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        backup = await request.app.state.store.logical_backup()
        result = await request.app.state.updater.create_update(
            version=body.version,
            backup_name=f"chronos-backup-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.json",
            backup_data=_backup_json(backup),
        )
        await request.app.state.store.audit(
            status="success",
            action="update.started",
            target=body.version,
            actor="operator",
            message="Chronos update handed to local Updater",
        )
        return result

    @app.get("/api/updates/jobs/{job_id}")
    async def update_job(
        request: Request, job_id: str, _: dict[str, Any] = Depends(operator)
    ):
        return await request.app.state.updater.job(job_id)

    @app.post("/api/updates/jobs/{job_id}/rollback")
    async def update_rollback(
        request: Request,
        job_id: str,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        result = await request.app.state.updater.rollback(job_id)
        await request.app.state.store.audit(
            status="success",
            action="update.rollback_started",
            target=job_id,
            actor="operator",
            message="Chronos rollback handed to local Updater",
        )
        return result

    web_dir = Path(__file__).resolve().parents[1] / "web" / "dist"
    assets_dir = web_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "API route not found"})
        requested = (web_dir / path).resolve()
        if web_dir.exists() and requested.is_relative_to(web_dir) and requested.is_file():
            return FileResponse(requested)
        index = web_dir / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"error": "Chronos web interface has not been built"},
        )

    return app


app = create_app()
