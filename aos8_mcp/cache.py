"""Short-lived in-memory cache for identical show invocations.

Tiered TTLs allow static-ish queries (``show version``) to live longer than
near-realtime ones (``show user-table``) while letting "realtime" commands
opt out of caching entirely.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal


CacheTier = Literal["static", "near_realtime", "realtime"]

_DEFAULT_TIER_TTL: dict[CacheTier, float] = {
    "static": 120.0,
    "near_realtime": 15.0,
    "realtime": 0.0,
}


class ShowResultCache:
    def __init__(self, default_ttl_seconds: float = 15.0) -> None:
        self._default_ttl = default_ttl_seconds
        self._tier_ttl: dict[CacheTier, float] = dict(_DEFAULT_TIER_TTL)
        self._data: dict[tuple[str, str, str], tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    def configure_default_ttl(self, ttl_seconds: float) -> None:
        """Override the fallback TTL used when no tier is specified."""
        self._default_ttl = max(0.0, ttl_seconds)
        # 让历史环境变量也作为 near_realtime 档的默认值，保持向后兼容
        self._tier_ttl["near_realtime"] = self._default_ttl

    def configure_tier_ttl(self, tier: CacheTier, ttl_seconds: float) -> None:
        self._tier_ttl[tier] = max(0.0, ttl_seconds)

    def ttl_for_tier(self, tier: CacheTier | None) -> float:
        if tier is None:
            return self._default_ttl
        return self._tier_ttl.get(tier, self._default_ttl)

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

    async def set(
        self,
        key: tuple[str, str, str],
        value: Any,
        ttl_seconds: float | None = None,
    ) -> None:
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            # 显式实时（或被禁用）档：不入缓存，并清理可能残留的旧条目
            async with self._lock:
                self._data.pop(key, None)
            return
        async with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)

    async def invalidate_session(self, session_id: str) -> None:
        async with self._lock:
            to_del = [k for k in self._data if k[0] == session_id]
            for k in to_del:
                del self._data[k]

    async def size(self) -> int:
        async with self._lock:
            return len(self._data)
