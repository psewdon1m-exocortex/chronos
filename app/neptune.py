from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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


@dataclass
class NeptuneClient:
    socket_path: str
    project_id: str
    control_token_file: Path
    last_known: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

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
                error = NeptuneError(str(result.get("error") or f"Neptune returned HTTP {response.status}"), response.status if response.status in {400, 404, 409, 410, 413, 422, 426, 503} else 502)
                error.upstream_status = response.status
                raise error
            return result
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as error:
            raise NeptuneError("Neptune is not installed or is unavailable on this VPS", 503) from error
        except (OSError, http.client.HTTPException) as error:
            raise NeptuneError(f"Neptune request failed: {error}") from error
        finally:
            connection.close()

    def _health(self) -> dict[str, Any]:
        connection = UnixHTTPConnection(self.socket_path, timeout=3)
        try:
            connection.request("GET", "/v1/health", headers={"Accept": "application/json", "Host": "neptune.local"})
            response = connection.getresponse()
            result = json.loads(response.read(1024 * 1024).decode("utf-8") or "{}")
            if not 200 <= response.status < 300 or not isinstance(result, dict):
                raise NeptuneError("Neptune health probe failed", 503)
            return result
        except (FileNotFoundError, ConnectionRefusedError, PermissionError, OSError, http.client.HTTPException, json.JSONDecodeError) as error:
            raise NeptuneError("Neptune is not installed or is unavailable on this VPS", 503) from error
        finally:
            connection.close()

    async def availability(self) -> dict[str, Any]:
        try:
            health = await asyncio.to_thread(self._health)
        except NeptuneError as error:
            return {"installed": None, "linked": None, **self.last_known, "state": "unavailable", "error": str(error)}
        try:
            status = await self.status()
            self.last_known = {**status, "installed": True, "linked": True, "state": "linked"}
            return self.last_known
        except NeptuneError as error:
            upstream = getattr(error, "upstream_status", None)
            state = "unlinked" if upstream == 404 else "authorization_failed" if upstream in {401, 403} else "unavailable"
            return {"linked": None, **self.last_known, "installed": True, "state": state, "version": health.get("version"),
                    **({"linked": False} if state == "unlinked" else {}), "error": str(error)}

    async def policy(self, method="GET", body=None, suffix=""):
        if method not in {"GET", "PUT", "POST"} or suffix not in {"", "/runs"}:
            raise NeptuneError("Unsupported backup policy operation", 400)
        return await asyncio.to_thread(self._request, method, "/policy" + suffix, body)

    async def status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "GET", "/status")

    async def schedule(self, enabled: bool, interval_hours: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "PUT", "/schedule", {"enabled": enabled, "intervalHours": interval_hours})

    async def run(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "POST", "/runs")
