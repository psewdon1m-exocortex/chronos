from __future__ import annotations

import asyncio
from dataclasses import dataclass
import http.client
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .updater import UnixHTTPConnection


class NeptuneError(RuntimeError):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class NeptuneClient:
    socket_path: str
    project_id: str
    control_token_file: Path

    def _request(self, method: str, route: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.control_token_file.is_file():
            raise NeptuneError("Neptune control token is not configured", 503)
        token = self.control_token_file.read_text(encoding="utf-8").strip()
        connection = UnixHTTPConnection(self.socket_path, timeout=30)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", "Host": "neptune.local", "X-Neptune-Token": token}
        if payload is not None:
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(payload))})
        target = f"/v1/projects/{quote(self.project_id, safe='')}{route}"
        try:
            connection.request(method, target, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise NeptuneError("Neptune response exceeds 1 MB")
            try:
                result = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise NeptuneError("Neptune returned invalid JSON") from error
            if not 200 <= response.status < 300:
                raise NeptuneError(str(result.get("error") or f"Neptune returned HTTP {response.status}"), 409 if response.status == 409 else 502)
            return result
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as error:
            raise NeptuneError("Neptune is not installed or is unavailable on this VPS", 503) from error
        except (OSError, http.client.HTTPException) as error:
            raise NeptuneError(f"Neptune request failed: {error}") from error
        finally:
            connection.close()

    async def status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "GET", "/status")

    async def schedule(self, enabled: bool, interval_hours: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "PUT", "/schedule", {"enabled": enabled, "intervalHours": interval_hours})

    async def run(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "POST", "/runs")
