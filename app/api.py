from __future__ import annotations

import asyncio
import csv
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta, timezone
import hashlib
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
    decrypt_service_secret,
    encrypt_service_secret,
    hash_password,
    new_csrf_token,
    new_link_code,
    validate_new_access_key,
    verify_password,
    verify_session_token,
)
from .store import Store
from .telemetry import TelemetrySampler
from .telegram import TelegramSupervisor
from .timer_service import TimerError, TimerService, timezone_for
from .updater import UpdaterClient, UpdaterError, check_github_release


LOGGER = logging.getLogger("chronos.api")
COOKIE_NAME = "chronos_session"
CSRF_COOKIE_NAME = "chronos_csrf"
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
SENSITIVE_ATTEMPTS: dict[str, list[float]] = {}
ROBOTS_POLICY = Path(__file__).with_name("robots.txt").read_text(encoding="utf-8")
PROXY_IDENTITY_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-real-ip",
    "cf-connecting-ip",
)
BLOCKED_PROBE_PATH = re.compile(
    r"(?:^|/)\.|\.(?:env|ini|log|sql|bak|backup|old|swp|zip|tar|gz)$",
    re.IGNORECASE,
)


class LoginInput(BaseModel):
    access_key: str = Field(min_length=1, max_length=1024)


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
    profile_name: str | None = Field(default=None, min_length=1, max_length=64)
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    week_starts_on: int | None = Field(default=None, ge=1, le=7)
    time_format: str | None = None
    date_format: str | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080)
    daily_summary_enabled: bool | None = None
    daily_summary_time: str | None = None
    theme_accent: str | None = None
    sidebar_auto_hide: bool | None = None
    navigation_order: list[str] | None = None
    dashboard_order: list[str] | None = None
    settings_order: list[str] | None = None


class AccessKeyInput(BaseModel):
    current_access_key: str = Field(min_length=1, max_length=1024)
    new_access_key: str = Field(min_length=12, max_length=1024)
    confirm_access_key: str = Field(min_length=12, max_length=1024)


class KernelUrlInput(BaseModel):
    kernel_url: str = Field(min_length=1, max_length=2048)


class KernelTokenInput(BaseModel):
    kernel_url: str = Field(min_length=1, max_length=2048)
    new_token: str = Field(min_length=24, max_length=4096)
    confirm_token: str = Field(min_length=24, max_length=4096)


class UpdateInput(BaseModel):
    version: str = Field(min_length=5, max_length=64)


def _request_id() -> str:
    return secrets.token_hex(12)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_proxied_request(request: Request) -> bool:
    return any(request.headers.get(name) for name in PROXY_IDENTITY_HEADERS)


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


def _check_sensitive_rate(request: Request, action: str) -> None:
    key = f"{action}:{_client_key(request)}"
    now = time_module.monotonic()
    attempts = [value for value in SENSITIVE_ATTEMPTS.get(key, []) if now - value < 300]
    if len(attempts) >= 10:
        raise HTTPException(status_code=429, detail="Too many credential changes. Try again later.")
    attempts.append(now)
    SENSITIVE_ATTEMPTS[key] = attempts


def _clear_sensitive_rate(request: Request, action: str) -> None:
    SENSITIVE_ATTEMPTS.pop(f"{action}:{_client_key(request)}", None)


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
    values = data.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="No settings were supplied")
    try:
        zone = values.get("timezone")
        if zone and zone != "UTC":
            ZoneInfo(zone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(status_code=400, detail="Unknown timezone") from error
    if "time_format" in values and values["time_format"] not in {"12h", "24h"}:
        raise HTTPException(status_code=400, detail="Unsupported time format")
    if "date_format" in values and values["date_format"] not in {"DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"}:
        raise HTTPException(status_code=400, detail="Unsupported date format")
    if "daily_summary_time" in values and not TIME_PATTERN.fullmatch(values["daily_summary_time"]):
        raise HTTPException(status_code=400, detail="Daily summary time must use HH:MM")
    if "theme_accent" in values and not COLOR_PATTERN.fullmatch(values["theme_accent"]):
        raise HTTPException(status_code=400, detail="Invalid accent color")
    orders = {
        "navigation_order": {"dashboard", "timeline", "analytics", "settings"},
        "dashboard_order": {"cpu", "ram", "disk", "uptime", "current", "today", "recent"},
        "settings_order": {
            "appearance", "security", "backup", "updates", "logs",
            "personalization", "telegram",
        },
    }
    for name, expected in orders.items():
        if name in values and (len(values[name]) != len(expected) or set(values[name]) != expected):
            raise HTTPException(status_code=400, detail=f"Invalid {name}")
    return values


def _normalize_kernel_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Kernel URL is invalid") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise HTTPException(status_code=400, detail="Kernel URL must be an HTTPS origin")
    return candidate


async def _validated_kernel_config(
    runtime: RuntimeState, *, kernel_url: str, kernel_token: str
) -> RuntimeConfig:
    candidate = runtime.config.with_kernel_credentials(
        kernel_url=kernel_url, kernel_service_token=kernel_token
    )
    try:
        snapshot = await asyncio.to_thread(
            load_snapshot, candidate, use_cache=False, write_cache=False
        )
        return apply_register(candidate, snapshot)
    except KernelRegisterError as error:
        raise HTTPException(
            status_code=400,
            detail="Kernel rejected the candidate connection or returned an invalid Register snapshot",
        ) from error


def _backup_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _backup_zip(value: dict[str, Any], version: str) -> bytes:
    payload = _backup_json(value)
    payload_name = "chronos-backup.json"
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(payload_name, payload)
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema": "exocortex.chronos.backup-manifest.v1",
                    "format": "logical-backup",
                    "schema_version": 1,
                    "service": "chronos",
                    "source_version": version,
                    "created_at": value["created_at"],
                    "scope": "complete",
                    "restore_mode": "replace",
                    "files": {
                        payload_name: {
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "uncompressed_bytes": len(payload),
                            "records": len(value.get("sessions", [])),
                        }
                    },
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
        kernel_url_seed=config.kernel_url,
        kernel_token_ciphertext_seed=encrypt_service_secret(
            config.kernel_service_token, config.session_secret
        ),
    )
    stored_kernel = await store.kernel_credentials()
    try:
        stored_kernel_token = decrypt_service_secret(
            str(stored_kernel["kernel_token_ciphertext"]), config.session_secret
        )
    except ValueError as error:
        raise RuntimeError(
            "Stored Kernel credential cannot be opened with CHRONOS_SESSION_SECRET"
        ) from error
    config = config.with_kernel_credentials(
        kernel_url=str(stored_kernel["kernel_url"]),
        kernel_service_token=stored_kernel_token,
    )
    validate_runtime_config(config)
    runtime = RuntimeState(config)
    timers = TimerService(store)
    telegram = TelegramSupervisor(runtime, store, timers)
    app.state.pool = pool
    app.state.store = store
    app.state.runtime = runtime
    app.state.timers = timers
    app.state.telegram = telegram
    app.state.telemetry = TelemetrySampler(config.data_dir)
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
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or _request_id()
        started = time_module.monotonic()
        if BLOCKED_PROBE_PATH.search(request.url.path):
            response = JSONResponse(status_code=404, content={"error": "Not found"})
        else:
            try:
                response = await call_next(request)
            except Exception:
                LOGGER.exception("Unhandled request error", extra={"request_id": request.state.request_id})
                raise
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
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

    @app.get("/robots.txt", include_in_schema=False)
    async def robots_txt():
        return Response(content=ROBOTS_POLICY, media_type="text/plain")

    @app.get("/api/health", include_in_schema=False)
    async def health(request: Request):
        if _is_proxied_request(request):
            raise HTTPException(status_code=404, detail="Not found")
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
        return {"accent": settings["theme_accent"]}

    @app.get("/api/public/reachability")
    async def public_reachability(request: Request):
        try:
            await request.app.state.pool.fetchval("select 1")
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "available"}

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        try:
            await operator(request)
        except HTTPException:
            return {"authenticated": False}
        security = await request.app.state.store.security()
        return {"authenticated": True}

    @app.post("/api/auth/login")
    async def login(request: Request, body: LoginInput):
        _check_login_rate(request)
        store: Store = request.app.state.store
        runtime: RuntimeState = request.app.state.runtime
        security = await store.security()
        valid = verify_password(body.access_key, str(security["password_hash"]))
        if not valid:
            await store.audit(
                status="denied",
                action="auth.login",
                target="operator",
                actor="anonymous",
                message="Invalid operator credentials",
                request_id=request.state.request_id,
            )
            raise HTTPException(status_code=401, detail="Invalid Access Key")
        _clear_login_rate(request)
        csrf = new_csrf_token()
        token = create_session_token(
            runtime.config.session_secret, int(security["session_generation"]), csrf
        )
        response = JSONResponse({"authenticated": True})
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
        end = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=zone)
        analytics = await timers.analytics(start, end, now=now)
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
            "telemetry": request.app.state.telemetry.sample(),
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
        stored_kernel = await request.app.state.store.kernel_credentials()
        return {
            "values": await request.app.state.store.settings(),
            "runtime": {
                "version": runtime.config.version,
                "public_url": runtime.config.public_url,
                "repository_url": runtime.config.repository_url,
                "register_revision": runtime.config.register_revision or None,
                "kernel_url": runtime.config.kernel_url or None,
                "kernel_reachable": bool(runtime.config.register_revision),
                "kernel_configured": bool(stored_kernel["kernel_token_ciphertext"]),
            },
            "telegram": {
                **request.app.state.telegram.status,
                "linked": bool(await request.app.state.store.telegram_owner_id()),
            },
        }

    @app.put("/api/settings")
    @app.patch("/api/settings")
    async def save_settings(
        request: Request,
        body: SettingsInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        changed = _validate_settings(body)
        values = await request.app.state.store.update_settings(changed)
        await request.app.state.store.audit(
            status="success",
            action="settings.updated",
            target="operator",
            actor="operator",
            message="Chronos setting updated",
            details={"keys": sorted(changed)},
            request_id=request.state.request_id,
        )
        return {"values": values}

    @app.post("/api/settings/reset-appearance")
    async def reset_appearance(
        request: Request, _: dict[str, Any] = Depends(mutation_operator)
    ):
        values = await request.app.state.store.update_settings(
            {"theme_accent": DEFAULT_SETTINGS["theme_accent"]}
        )
        await request.app.state.store.audit(
            status="success",
            action="appearance.reset",
            target="theme",
            actor="operator",
            message="Appearance reset to defaults",
        )
        return {"values": values}

    @app.post("/api/security/access-key")
    async def change_access_key(
        request: Request,
        body: AccessKeyInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        _check_sensitive_rate(request, "access-key")
        store: Store = request.app.state.store
        security = await store.security()
        if not verify_password(body.current_access_key, str(security["password_hash"])):
            await store.audit(
                status="denied",
                action="security.access_key_change",
                actor="operator",
                message="Current Access Key verification failed",
            )
            raise HTTPException(status_code=400, detail="Current Access Key is incorrect")
        if not hmac.compare_digest(body.new_access_key, body.confirm_access_key):
            raise HTTPException(status_code=400, detail="New Access Key entries do not match")
        try:
            validate_new_access_key(body.new_access_key)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        generation = await store.update_password(hash_password(body.new_access_key))
        csrf = new_csrf_token()
        token = create_session_token(
            request.app.state.runtime.config.session_secret, generation, csrf
        )
        response = JSONResponse({"changed": True})
        _set_session_cookies(response, request.app.state.runtime.config, token, csrf)
        await store.audit(
            status="success",
            action="security.access_key_change",
            target="operator",
            actor="operator",
            message="Operator Access Key changed",
        )
        _clear_sensitive_rate(request, "access-key")
        return response

    @app.put("/api/security/kernel-url")
    async def change_kernel_url(
        request: Request,
        body: KernelUrlInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        _check_sensitive_rate(request, "kernel-url")
        store: Store = request.app.state.store
        runtime: RuntimeState = request.app.state.runtime
        kernel_url = _normalize_kernel_url(body.kernel_url)
        if not runtime.config.kernel_service_token:
            raise HTTPException(
                status_code=409,
                detail="Rotate the Kernel token to validate and activate this URL",
            )
        try:
            updated = await _validated_kernel_config(
                runtime,
                kernel_url=kernel_url,
                kernel_token=runtime.config.kernel_service_token,
            )
        except HTTPException:
            await store.audit(
                status="error",
                action="security.kernel_url_change",
                target=kernel_url,
                actor="operator",
                message="Candidate Kernel URL validation failed",
                request_id=request.state.request_id,
            )
            raise
        await store.update_kernel_credentials(kernel_url=kernel_url)
        await runtime.replace(updated)
        await store.audit(
            status="success",
            action="security.kernel_url_change",
            target=kernel_url,
            actor="operator",
            message="Kernel URL validated and activated",
            request_id=request.state.request_id,
        )
        _clear_sensitive_rate(request, "kernel-url")
        return {"kernel_url": updated.kernel_url, "kernel_reachable": True}

    @app.post("/api/security/kernel-token")
    async def rotate_kernel_token(
        request: Request,
        body: KernelTokenInput,
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        _check_sensitive_rate(request, "kernel-token")
        store: Store = request.app.state.store
        runtime: RuntimeState = request.app.state.runtime
        kernel_url = _normalize_kernel_url(body.kernel_url)
        if not hmac.compare_digest(body.new_token, body.confirm_token):
            await store.audit(
                status="denied",
                action="security.kernel_token_rotation",
                target=kernel_url,
                actor="operator",
                message="Kernel token confirmation did not match",
                request_id=request.state.request_id,
            )
            raise HTTPException(status_code=400, detail="Kernel token entries do not match")
        try:
            updated = await _validated_kernel_config(
                runtime, kernel_url=kernel_url, kernel_token=body.new_token
            )
        except HTTPException:
            await store.audit(
                status="error",
                action="security.kernel_token_rotation",
                target=kernel_url,
                actor="operator",
                message="Replacement Kernel token validation failed",
                request_id=request.state.request_id,
            )
            raise
        ciphertext = encrypt_service_secret(body.new_token, runtime.config.session_secret)
        await store.update_kernel_credentials(
            kernel_url=kernel_url, kernel_token_ciphertext=ciphertext
        )
        await runtime.replace(updated)
        await store.audit(
            status="success",
            action="security.kernel_token_rotation",
            target=kernel_url,
            actor="operator",
            message="Kernel token validated and rotated",
            request_id=request.state.request_id,
        )
        _clear_sensitive_rate(request, "kernel-token")
        return {"changed": True, "kernel_url": updated.kernel_url, "kernel_reachable": True}

    @app.post("/api/telegram/link-code")
    async def telegram_link_code(
        request: Request, _: dict[str, Any] = Depends(mutation_operator)
    ):
        if await request.app.state.store.telegram_owner_id():
            raise HTTPException(status_code=409, detail="Telegram is already linked")
        code = new_link_code()
        expires_at = await request.app.state.store.create_link_code(code)
        await request.app.state.store.audit(
            status="info",
            action="telegram.link_code_created",
            target="owner",
            actor="operator",
            message="One-time Telegram link code created",
        )
        return {"code": code, "expires_at": expires_at.isoformat(), "expires_in_seconds": 600}

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
                    if len(names) > 16 or len(names) != len(set(names)):
                        raise ValueError("Archive member list is invalid")
                    if "chronos-backup.json" not in names:
                        raise ValueError("Archive does not contain chronos-backup.json")
                    if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                        raise ValueError("Archive contains an unsafe path")
                    allowed = {"chronos-backup.json", "manifest.json", "README.txt"}
                    if any(name not in allowed for name in names):
                        raise ValueError("Archive contains an unknown member")
                    total_size = sum(item.file_size for item in archive.infolist())
                    if total_size > 128 * 1024 * 1024:
                        raise ValueError("Archive expands beyond 128 MB")
                    if any(item.file_size > 64 * 1024 * 1024 for item in archive.infolist()):
                        raise ValueError("Archive member exceeds 64 MB")
                    raw = archive.read("chronos-backup.json")
                    if "manifest.json" in names:
                        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                        entry = manifest.get("files", {}).get("chronos-backup.json", {})
                        if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
                            raise ValueError("Backup checksum does not match the manifest")
            else:
                raw = body
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
            raise HTTPException(status_code=400, detail=f"Invalid Chronos backup: {error}") from error

    @app.post("/api/backup/inspect")
    async def inspect_backup(
        file: UploadFile = File(...),
        _: dict[str, Any] = Depends(mutation_operator),
    ):
        backup = await parse_backup_upload(file)
        sessions = backup.get("sessions")
        if backup.get("schema") != "exocortex.chronos.backup.v1" or not isinstance(sessions, list):
            raise HTTPException(status_code=400, detail="Unsupported or incomplete Chronos backup")
        return {
            "schema": backup["schema"],
            "created_at": backup.get("created_at"),
            "session_count": len(sessions),
            "restore_mode": "replace",
        }

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
        request: Request,
        limit: int = 200,
        after_id: int | None = None,
        _: dict[str, Any] = Depends(operator),
    ):
        events = await request.app.state.store.audit_events(min(limit, 1000), after_id=after_id)
        return {"events": events, "cursor": max((event["id"] for event in events), default=after_id or 0)}

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
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store, private",
            },
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
        backup_data = _backup_zip(backup, request.app.state.runtime.config.version)
        result = await request.app.state.updater.create_update(
            version=body.version,
            backup_name=f"chronos-backup-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.zip",
            backup_data=backup_data,
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
        if not path and index.exists():
            return FileResponse(index)
        if not path:
            return JSONResponse(
                status_code=503,
                content={"error": "Chronos web interface has not been built"},
            )
        return JSONResponse(status_code=404, content={"error": "Not found"})

    return app


app = create_app()
