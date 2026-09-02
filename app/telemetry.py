from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import time
from typing import Any


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _memory_total() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _process_rss() -> int | None:
    try:
        pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[1])
        return pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError, AttributeError):
        return None


class TelemetrySampler:
    """Small, privilege-free sampler for the running Chronos instance."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.started_at = time.monotonic()
        self.last_wall = time.monotonic()
        self.last_cpu = self._cpu_usage_seconds()

    @staticmethod
    def _cpu_usage_seconds() -> float:
        cpu_stat = Path("/sys/fs/cgroup/cpu.stat")
        try:
            for line in cpu_stat.read_text(encoding="ascii").splitlines():
                if line.startswith("usage_usec "):
                    return int(line.split()[1]) / 1_000_000
        except (OSError, ValueError, IndexError):
            pass
        return time.process_time()

    @staticmethod
    def _logical_cores() -> int:
        try:
            quota, period = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii").split()
            if quota != "max":
                return max(1, math.ceil(int(quota) / int(period)))
        except (OSError, ValueError, IndexError):
            pass
        return max(1, os.cpu_count() or 1)

    @staticmethod
    def _memory() -> tuple[int | None, int | None]:
        current = _read_int(Path("/sys/fs/cgroup/memory.current"))
        maximum_path = Path("/sys/fs/cgroup/memory.max")
        maximum: int | None = None
        try:
            raw = maximum_path.read_text(encoding="ascii").strip()
            if raw != "max":
                maximum = int(raw)
        except (OSError, ValueError):
            pass
        return current if current is not None else _process_rss(), maximum or _memory_total()

    def sample(self) -> dict[str, Any]:
        now = time.monotonic()
        cpu_now = self._cpu_usage_seconds()
        elapsed = now - self.last_wall
        cores = self._logical_cores()
        cpu_percent = None
        if elapsed >= 0.2:
            cpu_percent = max(0.0, min(100.0, (cpu_now - self.last_cpu) / elapsed / cores * 100))
        self.last_wall = now
        self.last_cpu = cpu_now

        memory_used, memory_total = self._memory()
        memory_percent = (
            max(0.0, min(100.0, memory_used / memory_total * 100))
            if memory_used is not None and memory_total
            else None
        )
        try:
            disk = shutil.disk_usage(self.data_dir)
            disk_used = disk.used
            disk_total = disk.total
            disk_percent = disk.used / disk.total * 100 if disk.total else None
        except OSError:
            disk_used = disk_total = disk_percent = None

        return {
            "captured_at": time.time(),
            "cpu": {"percent": cpu_percent, "logical_cores": cores},
            "ram": {
                "percent": memory_percent,
                "used_bytes": memory_used,
                "total_bytes": memory_total,
            },
            "disk": {
                "percent": disk_percent,
                "used_bytes": disk_used,
                "total_bytes": disk_total,
                "scope": str(self.data_dir),
            },
            "uptime_seconds": max(0, int(now - self.started_at)),
        }
