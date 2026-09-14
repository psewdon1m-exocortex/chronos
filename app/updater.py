from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import hashlib
import http.client
import json
import re
import socket
from uuid import uuid4
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


class UpdaterError(RuntimeError):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 10) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(self.socket_path)
        self.sock = connection


@dataclass(frozen=True)
class UpdaterClient:
    socket_path: str
    control_token: str
    head_id: str

    def _request(
        self,
        method: str,
        route: str,
        body: dict[str, Any] | None = None,
        authenticated: bool = False,
        timeout: float = 10,
    ) -> dict[str, Any]:
        connection = UnixHTTPConnection(self.socket_path, timeout=timeout)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", "Host": "updater.local"}
        if payload is not None:
            headers.update(
                {"Content-Type": "application/json", "Content-Length": str(len(payload))}
            )
        if authenticated:
            headers["X-Updater-Token"] = self.control_token
        try:
            connection.request(method, route, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise UpdaterError("Updater response exceeds 4 MB")
            try:
                result = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise UpdaterError("Updater returned invalid JSON") from error
            if not 200 <= response.status < 300:
                raise UpdaterError(
                    str(result.get("error") or f"Updater returned HTTP {response.status}"),
                    409 if response.status == 409 else 502,
                )
            return result
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as error:
            raise UpdaterError("Updater is not installed or is unavailable on this VPS", 503) from error
        except (OSError, http.client.HTTPException) as error:
            raise UpdaterError(f"Updater request failed: {error}") from error
        finally:
            connection.close()

    async def status(self) -> dict[str, Any]:
        try:
            value = await asyncio.to_thread(self._request, "GET", "/v1/health")
            return {"installed": True, "available": True, **value}
        except UpdaterError as error:
            if error.status == 503:
                return {
                    "installed": False,
                    "available": False,
                    "status": "unavailable",
                    "message": str(error),
                }
            raise

    async def create_update(
        self,
        *,
        version: str,
        backup_name: str,
        backup_data: bytes,
    ) -> dict[str, Any]:
        checksum = hashlib.sha256(backup_data).hexdigest()
        request_id = hashlib.sha256(
            f"{self.head_id}:{version}:{checksum}".encode("utf-8")
        ).hexdigest()[:32]
        body = {
            "request_id": request_id,
            "head_id": self.head_id,
            "service": "chronos",
            "version": version,
            "backup": {
                "filename": backup_name,
                "sha256": checksum,
                "data_base64": base64.b64encode(backup_data).decode("ascii"),
            },
        }
        return await asyncio.to_thread(
            self._request, "POST", "/v1/updates", body, True, 30
        )

    async def update_neptune(self, version: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/components/neptune-linux/update",
            {"head_id": self.head_id, "version": version},
            True,
            300,
        )

    async def check_neptune(self, current_version: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "POST", "/v1/components/neptune-linux/check",
            {"head_id": self.head_id, "current_version": current_version}, True, 30)

    async def lifecycle(self, kind: str, **fields: str) -> dict[str, Any]:
        if kind not in {"gryphon-initialization", "gryphon-bot", "updater-self-update"}:
            raise UpdaterError("Unsupported lifecycle operation", 400)
        return await asyncio.to_thread(self._request, "POST", f"/v1/lifecycle/{kind}",
            {"head_id": self.head_id, **fields}, True, 30)

    async def initialize_neptune(self, enrollment_code: str, export_url: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/components/neptune-linux/initialize",
            {
                "request_id": str(uuid4()),
                "head_id": self.head_id,
                "project_id": "chronos",
                "export_url": export_url,
                "enrollment_code": enrollment_code,
            },
            True,
            30,
        )

    async def update_gryphon(self, version: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/components/gryphon-linux/update",
            {"head_id": self.head_id, "version": version},
            True,
            300,
        )

    async def check_gryphon(self, current_version: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/components/gryphon-linux/check",
            {"head_id": self.head_id, "current_version": current_version},
            True,
            30,
        )

    async def job(self, job_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request, "GET", f"/v1/jobs/{quote(job_id, safe='')}", None, True
        )

    async def rollback(self, job_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request,
            "POST",
            f"/v1/jobs/{quote(job_id, safe='')}/rollback",
            {},
            True,
        )


def _version_tuple(value: str) -> tuple[int, int, int, str] | None:
    match = SEMVER.fullmatch(value.strip())
    if not match:
        return None
    return int(match[1]), int(match[2]), int(match[3]), match[4] or ""


async def check_github_release(
    repository_url: str,
    current_version: str,
    timeout_seconds: float,
    service: str = "chronos",
) -> dict[str, Any]:
    parsed = urlparse(repository_url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if parsed.scheme != "https" or parsed.hostname != "github.com" or len(segments) != 2:
        raise UpdaterError("Chronos repository must be an HTTPS GitHub repository", 400)
    owner, repository = segments
    repository = repository.removesuffix(".git")

    def fetch() -> list[dict[str, Any]]:
        request = Request(
            f"https://api.github.com/repos/{quote(owner)}/{quote(repository)}/releases?per_page=100",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"exocortex-{service}-updater",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))

    try:
        releases = await asyncio.to_thread(fetch)
    except Exception as error:
        raise UpdaterError(f"GitHub release check failed: {error}") from error
    candidates: list[tuple[tuple[int, int, int, str], dict[str, Any], str]] = []
    for release in releases:
        tag = str(release.get("tag_name") or "")
        if (
            release.get("draft")
            or release.get("prerelease")
            or not tag.lower().startswith(f"{service.lower()}-v")
        ):
            continue
        version = tag[len(service) + 2 :]
        parsed_version = _version_tuple(version)
        if parsed_version:
            candidates.append((parsed_version, release, version))
    candidates.sort(key=lambda item: item[0], reverse=True)
    available = candidates[0] if candidates else None
    current = _version_tuple(current_version) or (0, 0, 0, "")
    return {
        "service": service,
        "repository_url": repository_url,
        "installed_version": current_version,
        "available_version": available[2] if available else None,
        "update_available": bool(available and available[0] > current),
        "tag": available[1].get("tag_name") if available else None,
        "release_url": available[1].get("html_url") if available else None,
        "published_at": available[1].get("published_at") if available else None,
        "prerelease": bool(available and available[1].get("prerelease")),
        "apply_via": "updater",
        "backup_required": True,
    }
