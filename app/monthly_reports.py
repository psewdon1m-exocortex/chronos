"""Durable month-end reports delivered to Mastermind through Kernel discovery."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import logging
import os
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPSHandler, Request, build_opener

from .kernel_register import KernelRegisterError, _NoRedirect, _resolve_kernel_values
from .timer_service import TimerService, timezone_for


LOGGER = logging.getLogger("chronos.monthly_reports")
SLOT = re.compile(r"\{\{([^{}\n]+)\}\}")
MONTH_NAMES = ("", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
               "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")


class MastermindReportError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MASTERMIND_UNAVAILABLE"):
        super().__init__(message)
        self.code = code


def _next_month(first: date) -> date:
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1)


def _last_completed_month(zone, now: datetime | None = None) -> date:
    current = (now or datetime.now(timezone.utc)).astimezone(zone).date().replace(day=1)
    return (current - timedelta(days=1)).replace(day=1)


def _duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, rest = divmod(remainder, 60)
    return f"{hours} ч {minutes:02d} мин" + (f" {rest:02d} с" if rest else "")


def render_report(template: str, month: date, zone_name: str, data: dict) -> str:
    """Replace fixed placeholders only; the template owns its literal @note link."""
    following = _next_month(month)
    days = (following - month).days
    categories = data["categories"]
    total = int(data["total_seconds"])
    category_rows = ["| Категория | Время | Доля учтённого |", "|:--|--:|--:|"]
    slices = []
    for item in categories:
        seconds = int(item["seconds"])
        category_rows.append(f'| {item["label"]} | {_duration(seconds)} | {item["percent"]:.2f} % |')
        if seconds:
            slices.append(f'    "{item["label"]}" : {seconds}')
    category_rows.append(f"| **Всего** | **{_duration(total)}** | **{100 if total else 0} %** |")
    category_chart = ("```mermaid\npie\n    title Доли учтённого времени\n" +
                      "\n".join(slices) + "\n```") if slices else "За этот месяц время не записано."
    daily = {item["date"]: int(item["total_seconds"]) for item in data["days"]}
    values = [daily.get((month + timedelta(days=offset)).isoformat(), 0) for offset in range(days)]
    chart_minutes = [round(value / 60) for value in values]
    ceiling = max(60, ((max(chart_minutes, default=0) + 59) // 60) * 60)
    daily_chart = ("```mermaid\nxychart-beta\n"
                   f'    title "Учтённое время по дням: {MONTH_NAMES[month.month].lower()} {month.year}"\n'
                   '    x-axis "День месяца" [' + ", ".join(str(i) for i in range(1, days + 1)) + "]\n"
                   f'    y-axis "Минуты" 0 --> {ceiling}\n'
                   "    bar [" + ", ".join(str(value) for value in chart_minutes) + "]\n```")
    daily_rows = ["| Дата | Учтено |", "|:--|--:|"]
    for offset, seconds in enumerate(values):
        day = month + timedelta(days=offset)
        daily_rows.append(f"| {day:%d.%m.%Y} | {_duration(seconds)} |")
    fields = {
        "chronos.month": f"{month:%Y-%m}",
        "chronos.month_title": f"{MONTH_NAMES[month.month]} {month.year}",
        "chronos.timezone": zone_name,
        "chronos.period": f"{month:%d.%m.%Y} 00:00 — {following:%d.%m.%Y} 00:00",
        "chronos.total": _duration(total),
        "chronos.days": str(days),
        "chronos.coverage": f'{data["coverage_percent"]:.2f} %',
        "chronos.category_chart": category_chart,
        "chronos.category_table": "\n".join(category_rows),
        "chronos.daily_chart": daily_chart,
        "chronos.daily_table": "\n".join(daily_rows),
    }
    rendered = SLOT.sub(lambda match: fields[match[1]], template)
    if "{{" in rendered or "}}" in rendered or len(rendered.encode("utf-8")) > 256 * 1024:
        raise ValueError("Monthly report template produced invalid Markdown")
    return rendered.rstrip() + "\n"


class MastermindReportClient:
    def __init__(self, runtime):
        self.runtime = runtime

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        config = self.runtime.config
        keys = ["services.mastermind.sni", "services.mastermind.port",
                "services.mastermind.secrets.chronos_report_token"]
        try:
            resolved = _resolve_kernel_values(config, keys)
            host, port, token = (resolved[key] for key in keys)
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host) \
                    or not re.fullmatch(r"\d{1,5}", port) or not 1 <= int(port) <= 65535 \
                    or not 1 <= len(token) <= 512:
                raise ValueError("Invalid Mastermind route or credential")
            ca_file = os.getenv("SSL_CERT_FILE") or None
            opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=ca_file)))
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
            request = Request(f"https://{host}:{port}{route}", data=body, method=method,
                              headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                                       "Accept-Encoding": "identity", **({"Content-Type": "application/json"} if body is not None else {})})
            with opener.open(request, timeout=10) as response:
                raw = response.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ValueError("Mastermind response exceeds limit")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Invalid Mastermind response")
            return value
        except HTTPError as error:
            try:
                detail = json.loads(error.read(8192).decode("utf-8")).get("error", {})
                code = str(detail.get("code", "MASTERMIND_REJECTED"))
                message = str(detail.get("message", "Mastermind rejected the report"))
            except (ValueError, UnicodeError, AttributeError):
                code, message = "MASTERMIND_REJECTED", "Mastermind rejected the report"
            raise MastermindReportError(message[:240], code=code) from None
        except (KernelRegisterError, URLError, OSError, ValueError, ssl.SSLError) as error:
            raise MastermindReportError("Mastermind connection through Kernel is unavailable") from error

    async def template(self, path: str) -> dict:
        value = await asyncio.to_thread(self._request, "GET", "/api/v1/internal/chronos/monthly-template?path=" + quote(path, safe=""))
        if value.get("path") != path or not isinstance(value.get("text"), str) \
                or not isinstance(value.get("anchor"), str) \
                or value.get("sha256") != hashlib.sha256(value["text"].encode("utf-8")).hexdigest():
            raise MastermindReportError("Mastermind returned an invalid report template")
        return value

    async def deliver(self, payload: dict) -> dict:
        value = await asyncio.to_thread(self._request, "POST", "/api/v1/internal/chronos/monthly-reports", payload)
        if value.get("path") != f'Chronos {payload["month"]}.md' \
                or value.get("sha256") != hashlib.sha256(payload["text"].encode("utf-8")).hexdigest():
            raise MastermindReportError("Mastermind returned an invalid report receipt")
        return value


class MonthlyReportSupervisor:
    def __init__(self, store, timers: TimerService, runtime, client: MastermindReportClient | None = None):
        self.store, self.timers, self.runtime = store, timers, runtime
        self.client = client or MastermindReportClient(runtime)
        self._stop = asyncio.Event()

    async def stop(self):
        self._stop.set()

    async def status(self) -> dict:
        settings = await self.store.settings()
        async with self.store.pool.acquire() as connection:
            rows = await connection.fetch("SELECT month,state,attempts,last_error,mastermind_path,delivered_at "
                                          "FROM monthly_reports ORDER BY month DESC LIMIT 12")
        return {"enabled": bool(settings["monthly_report_enabled"]),
                "template_path": settings["monthly_report_template_path"],
                "reports": [{**dict(row), "delivered_at": row["delivered_at"].isoformat()
                             if row["delivered_at"] else None} for row in rows]}

    async def ensure_due(self, now: datetime | None = None) -> None:
        settings = await self.store.settings()
        if not settings["monthly_report_enabled"] or not settings["monthly_report_template_path"]:
            return
        zone = timezone_for(str(settings["timezone"]))
        last = _last_completed_month(zone, now)
        since = settings.get("monthly_report_since") or last.strftime("%Y-%m")
        first = date.fromisoformat(since + "-01")
        if first > last:
            return
        async with self.store.pool.acquire() as connection:
            while first <= last:
                await connection.execute("INSERT INTO monthly_reports(month,timezone,template_path,state) "
                                         "VALUES($1,$2,$3,'pending') ON CONFLICT(month) DO NOTHING",
                                         first.strftime("%Y-%m"), settings["timezone"], settings["monthly_report_template_path"])
                first = _next_month(first)

    async def _claim(self, *, force_retry: bool = False):
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow("SELECT * FROM monthly_reports WHERE "
                    "(state='pending' AND (next_attempt_at <= now() OR $1::boolean)) OR "
                    "(state='processing' AND lease_until < now()) "
                    "ORDER BY month LIMIT 1 FOR UPDATE SKIP LOCKED", force_retry)
                if row is None:
                    return None
                return await connection.fetchrow("UPDATE monthly_reports SET state='processing', "
                    "attempts=attempts+1, lease_until=now()+interval '5 minutes', updated_at=now() "
                    "WHERE month=$1 RETURNING *", row["month"])

    async def run_once(self, now: datetime | None = None, *, force_retry: bool = False) -> dict | None:
        await self.ensure_due(now)
        settings = await self.store.settings()
        if not settings["monthly_report_enabled"]:
            return None
        row = await self._claim(force_retry=force_retry)
        if row is None:
            return None
        month = str(row["month"])
        try:
            body, template_sha = row["body"], row["template_sha256"]
            if not body:
                template = await self.client.template(row["template_path"])
                first = date.fromisoformat(month + "-01")
                zone = timezone_for(row["timezone"])
                start = datetime.combine(first, time.min, tzinfo=zone)
                end = datetime.combine(_next_month(first), time.min, tzinfo=zone)
                analytics = await self.timers.analytics(start, end)
                body = render_report(template["text"], first, row["timezone"], analytics)
                template_sha = template["sha256"]
                async with self.store.pool.acquire() as connection:
                    await connection.execute("UPDATE monthly_reports SET body=$2,template_sha256=$3,updated_at=now() "
                                             "WHERE month=$1 AND state='processing'", month, body, template_sha)
            if not (await self.store.settings())["monthly_report_enabled"]:
                raise MastermindReportError("Monthly reports were disabled")
            receipt = await self.client.deliver({"month": month, "timezone": row["timezone"],
                "template_path": row["template_path"], "template_sha256": template_sha, "text": body})
            async with self.store.pool.acquire() as connection:
                await connection.execute("UPDATE monthly_reports SET state='delivered',mastermind_path=$2,"
                    "delivered_at=now(),lease_until=NULL,last_error='',body=NULL,updated_at=now() WHERE month=$1",
                    month, receipt["path"])
            try:
                await self.store.audit(status="success", action="monthly_report.delivered", target=month,
                                       actor="system", message="Monthly Chronos report delivered to Mastermind",
                                       details={"path": receipt["path"]})
            except Exception:
                LOGGER.exception("Monthly report %s was delivered but audit recording failed", month)
            return receipt
        except Exception as error:
            LOGGER.warning("Monthly report %s failed: %s", month, error)
            clear = isinstance(error, MastermindReportError) and error.code == "REPORT_TEMPLATE_CHANGED"
            delay = min(3600, 30 * 2 ** min(int(row["attempts"]), 7))
            async with self.store.pool.acquire() as connection:
                await connection.execute("UPDATE monthly_reports SET state='pending',lease_until=NULL,"
                    "next_attempt_at=now()+($2::int * interval '1 second'),last_error=$3,"
                    "body=CASE WHEN $4 THEN NULL ELSE body END,"
                    "template_sha256=CASE WHEN $4 THEN NULL ELSE template_sha256 END,updated_at=now() "
                    "WHERE month=$1", month, delay, str(error)[:240], clear)
            return None

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                LOGGER.exception("Monthly report supervisor failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
            except TimeoutError:
                pass
