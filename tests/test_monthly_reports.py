from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.monthly_reports import MastermindReportClient, MastermindReportError, MonthlyReportSupervisor, _last_completed_month, render_report


TEMPLATE = (Path(__file__).resolve().parents[1] / "docs" / "examples" /
            "chronos-monthly-template.md").read_text(encoding="utf-8")


def analytics_data() -> dict:
    return {
        "total_seconds": 5400,
        "coverage_percent": 5400 / (30 * 86400) * 100,
        "categories": [
            {"label": "Recovery", "seconds": 3600, "percent": 66.67},
            {"label": "Accumulation", "seconds": 1800, "percent": 33.33},
            {"label": "Execution", "seconds": 0, "percent": 0.0},
            {"label": "Maintenance", "seconds": 0, "percent": 0.0},
        ],
        "days": [{"date": "2026-09-30", "total_seconds": 5400}],
    }


def test_month_boundary_uses_profile_timezone() -> None:
    zone = ZoneInfo("Europe/Istanbul")
    assert _last_completed_month(zone, datetime(2026, 9, 30, 20, 59, tzinfo=timezone.utc)) == date(2026, 8, 1)
    assert _last_completed_month(zone, datetime(2026, 9, 30, 21, 1, tzinfo=timezone.utc)) == date(2026, 9, 1)


def test_render_report_preserves_graph_link_and_calendar_days() -> None:
    body = render_report(TEMPLATE, date(2026, 9, 1), "Europe/Istanbul", analytics_data())
    assert "@chronos_analytics" in body
    assert 'period: "2026-09"' in body
    assert "1 ч 30 мин" in body
    assert '"Recovery" : 3600' in body
    assert "| 30.09.2026 | 1 ч 30 мин |" in body
    assert "{{" not in body


@pytest.mark.asyncio
async def test_mastermind_client_verifies_template_and_receipt_hashes() -> None:
    client = MastermindReportClient(SimpleNamespace())
    path = "root/templates/chronos_note.md"
    client._request = lambda *_: {"path": path, "text": TEMPLATE, "anchor": "chronos_analytics.md",
                                  "sha256": hashlib.sha256(TEMPLATE.encode()).hexdigest()}
    assert (await client.template(path))["text"] == TEMPLATE
    client._request = lambda *_: {"path": path, "text": TEMPLATE, "anchor": "chronos_analytics.md",
                                  "sha256": "0" * 64}
    with pytest.raises(MastermindReportError, match="invalid report template"):
        await client.template(path)

    payload = {"month": "2026-09", "text": "# report\n"}
    client._request = lambda *_: {"path": "Chronos 2026-09.md", "sha256": "0" * 64}
    with pytest.raises(MastermindReportError, match="invalid report receipt"):
        await client.deliver(payload)


class FakePool:
    def __init__(self):
        self.connection = SimpleNamespace(execute=AsyncMock())

    def acquire(self):
        pool = self

        class Lease:
            async def __aenter__(self):
                return pool.connection

            async def __aexit__(self, *_):
                return None

        return Lease()


@pytest.mark.asyncio
async def test_supervisor_renders_then_delivers_one_note() -> None:
    pool = FakePool()
    store = SimpleNamespace(pool=pool, settings=AsyncMock(return_value={"monthly_report_enabled": True}),
                            audit=AsyncMock())
    timers = SimpleNamespace(analytics=AsyncMock(return_value=analytics_data()))
    client = SimpleNamespace(template=AsyncMock(return_value={"text": TEMPLATE, "sha256": "a" * 64}),
                             deliver=AsyncMock(return_value={"path": "Chronos 2026-09.md", "sha256": "b" * 64}))
    supervisor = MonthlyReportSupervisor(store, timers, SimpleNamespace(), client)
    supervisor.ensure_due = AsyncMock()
    supervisor._claim = AsyncMock(return_value={
        "month": "2026-09", "timezone": "Europe/Istanbul", "template_path": "root/templates/chronos_note.md",
        "body": None, "template_sha256": None, "attempts": 1,
    })

    receipt = await supervisor.run_once()

    assert receipt["path"] == "Chronos 2026-09.md"
    start, end = timers.analytics.await_args.args
    assert start.isoformat() == "2026-09-01T00:00:00+03:00"
    assert end.isoformat() == "2026-10-01T00:00:00+03:00"
    payload = client.deliver.await_args.args[0]
    assert payload["template_sha256"] == "a" * 64
    assert "@chronos_analytics" in payload["text"]
    assert pool.connection.execute.await_count == 2
    assert "state='delivered'" in pool.connection.execute.await_args_list[1].args[0]
    store.audit.assert_awaited_once()
