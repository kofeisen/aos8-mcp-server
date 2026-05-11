"""Short-lived in-memory cache for identical show invocations."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class ShowResultCache:
    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._data: dict[tuple[str, str, str], tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    def configure_ttl(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds

    async def get(self, key: tuple[str, str, str]) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            exp, payload = entry
            if time.monotonic() > exp:
                del self._data[key]
                return None
            return payload

    async def set(self, key: tuple[str, str, str], value: Any) -> None:
        async with self._lock:
            self._data[key] = (time.monotonic() + self._ttl, value)

    async def invalidate_session(self, session_id: str) -> None:
        async with self._lock:
            to_del = [k for k in self._data if k[0] == session_id]
            for k in to_del:
                del self._data[k]
