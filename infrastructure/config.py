from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    name: str
    user: str
    password: str
    sslmode: str


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    db: DbConfig


def load_config() -> AppConfig:
    db = DbConfig(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        name=os.getenv("DB_NAME", "chronos"),
        user=os.getenv("DB_USER", "chronos"),
        password=os.getenv("DB_PASSWORD", ""),
        sslmode=os.getenv("DB_SSLMODE", "disable"),
    )
    return AppConfig(
        timezone=os.getenv("TZ", "UTC"),
        db=db,
    )
