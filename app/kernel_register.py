from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import RuntimeConfig


SNAPSHOT_SCHEMA = "exocortex.register.snapshot.v1"
REVISION_PATTERN = re.compile(r"^register-[A-Za-z0-9-]+$")
TELEGRAM_TOKEN_PATTERN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")


class KernelRegisterError(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _verify_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise KernelRegisterError("unsupported Kernel Register schema")
    revision = snapshot.get("revision")
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise KernelRegisterError("invalid Kernel Register revision")
    values = snapshot.get("values")
    if not isinstance(values, dict):
        raise KernelRegisterError("Kernel Register values must be an object")
    expected = "sha256:" + hashlib.sha256(
        _canonical_json({"values": values}).encode("utf-8")
    ).hexdigest()
    if snapshot.get("checksum") != expected:
        raise KernelRegisterError("Kernel Register checksum mismatch")
    return snapshot


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        return _verify_snapshot(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as error:
        raise KernelRegisterError("no valid Kernel Register last-known-good cache") from error


def _write_cache(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(_canonical_json(snapshot) + "\n", encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        _read_cache(temporary)
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def _resolve(values: dict[str, Any], key: str) -> Any:
    cursor: Any = values
    for part in key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def _first_string(values: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _resolve(values, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _registered_kernel_url(snapshot: dict[str, Any], bootstrap_url: str) -> str:
    values = snapshot["values"]
    sni = _first_string(values, ("services.kernel.sni",))
    port_value = _first_string(values, ("services.kernel.port",))
    if not sni or not port_value:
        return bootstrap_url
    try:
        port = int(port_value)
    except ValueError:
        return bootstrap_url
    if not 1 <= port <= 65535:
        return bootstrap_url
    parsed = urlparse(bootstrap_url)
    check = urlparse(f"http://{sni}")
    if parsed.scheme not in {"http", "https"} or not check.hostname:
        return bootstrap_url
    host = f"[{sni}]" if ":" in sni and not sni.startswith("[") else sni
    public_port = "" if port == 443 else f":{port}"
    return parsed._replace(
        netloc=f"{host}{public_port}", path="", params="", query="", fragment=""
    ).geturl()


def load_snapshot(
    config: RuntimeConfig, *, use_cache: bool = True, write_cache: bool = True
) -> dict[str, Any]:
    if not config.kernel_url and not config.kernel_service_token:
        return {}
    if not config.kernel_url or not config.kernel_service_token:
        raise KernelRegisterError(
            "KERNEL_URL and KERNEL_SERVICE_TOKEN must be configured together"
        )
    cached: dict[str, Any] | None = None
    if use_cache:
        try:
            cached = _read_cache(config.kernel_cache_path)
        except KernelRegisterError:
            pass
    headers = {
        "Authorization": f"Bearer {config.kernel_service_token}",
        "Accept": "application/vnd.exocortex.register+json; version=1",
        "User-Agent": f"exocortex-chronos/{config.version}",
    }
    if cached:
        headers["If-None-Match"] = f'"{cached["revision"]}"'
    urls = [config.kernel_url.rstrip("/")]
    if cached:
        registered = _registered_kernel_url(cached, config.kernel_url).rstrip("/")
        if registered not in urls:
            urls.insert(0, registered)
    last_error: Exception | None = None
    for remote_url in urls:
        request = Request(
            f"{remote_url}/api/v1/register/snapshot", headers=headers, method="GET"
        )
        try:
            with urlopen(request, timeout=config.kernel_timeout_seconds) as response:
                body = response.read(3 * 1024 * 1024 + 1)
                if len(body) > 3 * 1024 * 1024:
                    raise KernelRegisterError("Kernel Register response is too large")
                snapshot = _verify_snapshot(json.loads(body.decode("utf-8")))
                if write_cache:
                    _write_cache(config.kernel_cache_path, snapshot)
                return snapshot
        except HTTPError as error:
            if error.code == 304 and cached:
                return cached
            last_error = error
        except (URLError, TimeoutError, OSError, ValueError, KernelRegisterError) as error:
            last_error = error
    if cached:
        return cached
    raise KernelRegisterError(
        "Kernel unavailable and no valid Register last-known-good cache exists"
    ) from last_error


def _https_url(value: str, key: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise KernelRegisterError(f"Kernel Register key {key} must be an HTTPS URL")
    return value.rstrip("/")


def _public_url(values: dict[str, Any], current: str) -> str:
    explicit = _first_string(values, ("services.chronos.url",))
    if explicit:
        return _https_url(explicit, "services.chronos.url")
    sni = _first_string(values, ("services.chronos.sni",))
    if not sni:
        return current
    parsed = urlparse(f"http://{sni}")
    if not parsed.hostname or parsed.port is not None or parsed.path not in {"", "/"}:
        raise KernelRegisterError("services.chronos.sni must contain only a hostname")
    port_value = _first_string(values, ("services.chronos.port",)) or "443"
    try:
        port = int(port_value)
    except ValueError as error:
        raise KernelRegisterError("services.chronos.port must be an integer") from error
    if not 1 <= port <= 65535:
        raise KernelRegisterError("services.chronos.port is outside the valid range")
    host = f"[{sni}]" if ":" in sni and not sni.startswith("[") else sni
    return f"https://{host}{'' if port == 443 else f':{port}'}"


def _secret_value(value: str) -> str:
    if value.startswith("secret://env/"):
        env_name = value.removeprefix("secret://env/")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", env_name):
            raise KernelRegisterError("invalid secret environment reference")
        return os.getenv(env_name, "").strip()
    return value


def apply_register(config: RuntimeConfig, snapshot: dict[str, Any]) -> RuntimeConfig:
    if not snapshot:
        return config
    values = snapshot["values"]
    repository = _first_string(values, ("repositories.chronos.url",))
    if repository:
        repository = _https_url(repository, "repositories.chronos.url")
    else:
        repository = config.repository_url
    telegram = _first_string(
        values,
        (
            "secrets.chronos.telegram_bot_token",
            "services.chronos.telegram_api",
            "services.chronos.telegram_bot_api",
        ),
    )
    telegram = _secret_value(telegram) if telegram else config.telegram_token
    if telegram and not TELEGRAM_TOKEN_PATTERN.fullmatch(telegram):
        raise KernelRegisterError("Chronos Telegram API token has an invalid format")
    refresh_value = _resolve(values, "intervals.kernel.refresh_sec")
    try:
        refresh = int(refresh_value)
    except (TypeError, ValueError):
        refresh = config.kernel_refresh_seconds
    refresh = refresh if 5 <= refresh <= 3600 else config.kernel_refresh_seconds
    return config.with_register(
        repository_url=repository,
        public_url=_public_url(values, config.public_url),
        telegram_token=telegram,
        register_revision=snapshot["revision"],
        kernel_refresh_seconds=refresh,
    )
