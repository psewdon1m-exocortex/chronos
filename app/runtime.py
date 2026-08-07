from __future__ import annotations

import asyncio

from .config import RuntimeConfig


class RuntimeState:
    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self.changed = asyncio.Event()

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    async def replace(self, config: RuntimeConfig) -> None:
        async with self._lock:
            changed = config != self._config
            self._config = config
            if changed:
                self.changed.set()

    def clear_change(self) -> None:
        self.changed.clear()

