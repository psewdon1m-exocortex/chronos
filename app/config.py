from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= minimum else default


@dataclass(frozen=True)
class RuntimeConfig:
    listen_port: int
    database_url: str
    admin_username: str
    admin_password: str
    session_secret: str
    cookie_secure: bool
    trust_proxy: bool
    version: str
    data_dir: Path
    default_timezone: str
    kernel_url: str
    kernel_service_token: str
    kernel_cache_path: Path
    kernel_timeout_seconds: float
    kernel_refresh_seconds: int
    repository_url: str
    public_url: str
    register_revision: str
    updater_socket_path: str
    updater_head_id: str
    updater_control_token: str
    update_check_timeout_seconds: float
    audit_max_entries: int
    audit_retention_days: int
    neptune_socket_path: str
    neptune_project_id: str
    neptune_control_token_file: Path
    neptune_export_token_file: Path
    gryphon_service_token_file: Path
    gryphon_socket_path: str
    gryphon_adapter_url: str
    gryphon_timeout_seconds: float
    storage_path: Path | None = None

    def with_register(
        self,
        *,
        repository_url: str,
        public_url: str,
        register_revision: str,
        kernel_refresh_seconds: int | None = None,
    ) -> "RuntimeConfig":
        return replace(
            self,
            repository_url=repository_url,
            public_url=public_url,
            register_revision=register_revision,
            kernel_refresh_seconds=kernel_refresh_seconds or self.kernel_refresh_seconds,
        )

    def with_kernel_credentials(
        self, *, kernel_url: str, kernel_service_token: str
    ) -> "RuntimeConfig":
        return replace(
            self,
            kernel_url=kernel_url,
            kernel_service_token=kernel_service_token,
            register_revision="",
        )


def load_config() -> RuntimeConfig:
    data_dir = Path(os.getenv("CHRONOS_DATA_DIR", ".data")).resolve()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        user = os.getenv("DB_USER", "chronos")
        password = os.getenv("DB_PASSWORD", "")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "chronos")
        database_url = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return RuntimeConfig(
        storage_path=Path(os.getenv("CHRONOS_STORAGE_PATH", str(data_dir))).resolve(),
        listen_port=_integer("CHRONOS_LISTEN_PORT", 18280),
        database_url=database_url,
        admin_username=os.getenv("CHRONOS_ADMIN_USERNAME", "operator") or "operator",
        admin_password=(
            os.getenv("CHRONOS_ACCESS_KEY", "").strip()
            or os.getenv("CHRONOS_ADMIN_PASSWORD", "")
        ),
        session_secret=os.getenv("CHRONOS_SESSION_SECRET", ""),
        cookie_secure=_boolean("CHRONOS_COOKIE_SECURE", True),
        trust_proxy=_boolean("CHRONOS_TRUST_PROXY", True),
        version=os.getenv("CHRONOS_VERSION", "0.1.1"),
        data_dir=data_dir,
        default_timezone=os.getenv("TZ", "UTC"),
        kernel_url=os.getenv("KERNEL_URL", "").strip(),
        kernel_service_token=os.getenv("KERNEL_SERVICE_TOKEN", "").strip(),
        kernel_cache_path=Path(
            os.getenv(
                "KERNEL_CACHE_PATH",
                str(data_dir / "kernel-cache" / "register.snapshot.json"),
            )
        ),
        kernel_timeout_seconds=float(os.getenv("KERNEL_TIMEOUT_SEC", "3")),
        kernel_refresh_seconds=_integer("KERNEL_REFRESH_SEC", 60, 5),
        repository_url=os.getenv("CHRONOS_REPOSITORY_URL", "").strip(),
        public_url=os.getenv("CHRONOS_PUBLIC_URL", "").strip(),
        register_revision="",
        updater_socket_path=os.getenv(
            "UPDATER_SOCKET_PATH", "/run/exocortex/updater.sock"
        ),
        updater_head_id=os.getenv("UPDATER_HEAD_ID", "chronos"),
        updater_control_token=os.getenv("UPDATER_CONTROL_TOKEN", ""),
        update_check_timeout_seconds=float(
            os.getenv("CHRONOS_UPDATE_CHECK_TIMEOUT_SEC", "5")
        ),
        audit_max_entries=_integer("CHRONOS_AUDIT_MAX_ENTRIES", 10000),
        audit_retention_days=_integer("CHRONOS_AUDIT_RETENTION_DAYS", 30),
        neptune_socket_path=os.getenv("NEPTUNE_SOCKET_PATH", "/run/neptune/neptuned.sock"),
        neptune_project_id=os.getenv("NEPTUNE_PROJECT_ID", "chronos"),
        neptune_control_token_file=Path(os.getenv("NEPTUNE_CONTROL_TOKEN_FILE", "/run/secrets/neptune/control.token")),
        neptune_export_token_file=Path(os.getenv("NEPTUNE_EXPORT_TOKEN_FILE", "/run/secrets/neptune/export.token")),
        gryphon_service_token_file=Path(
            os.getenv(
                "GRYPHON_SERVICE_TOKEN_FILE",
                "/run/secrets/gryphon/chronos.token",
            )
        ),
        gryphon_socket_path=os.getenv("GRYPHON_SOCKET_PATH", "/run/gryphon/client.sock"),
        gryphon_adapter_url=os.getenv(
            "GRYPHON_ADAPTER_URL",
            "",
        ),
        gryphon_timeout_seconds=float(os.getenv("GRYPHON_TIMEOUT_SEC", "5")),
    )


def validate_runtime_config(config: RuntimeConfig) -> None:
    issues: list[str] = []
    if len(config.admin_password) < 12 or config.admin_password == "CHANGE_ME":
        issues.append("CHRONOS_ACCESS_KEY must contain at least 12 characters")
    if len(config.session_secret) < 32 or config.session_secret.startswith("replace-"):
        issues.append("CHRONOS_SESSION_SECRET must contain at least 32 characters")
    if not config.database_url.startswith(("postgresql://", "postgres://")):
        issues.append("DATABASE_URL must be a PostgreSQL URL")
    if bool(config.kernel_url) != bool(config.kernel_service_token):
        issues.append("KERNEL_URL and KERNEL_SERVICE_TOKEN must be configured together")
    if issues:
        raise RuntimeError("; ".join(issues))
