"""Tests for the tiered ShowResultCache."""

from __future__ import annotations

import asyncio

import pytest

from aos8_mcp.cache import ShowResultCache


@pytest.mark.asyncio
async def test_set_and_get_roundtrip() -> None:
    c = ShowResultCache()
    key = ("sid", "host", "show version")
    await c.set(key, {"raw": 1}, ttl_seconds=5)
    hit = await c.get(key)
    assert hit == {"raw": 1}


@pytest.mark.asyncio
async def test_realtime_tier_does_not_store() -> None:
    c = ShowResultCache()
    key = ("sid", "host", "show cpuload")
    await c.set(key, {"raw": 1}, ttl_seconds=0)
    assert await c.get(key) is None


@pytest.mark.asyncio
async def test_expired_entry_is_dropped() -> None:
    c = ShowResultCache()
    key = ("sid", "host", "show vlan")
    await c.set(key, {"raw": 1}, ttl_seconds=0.01)
    await asyncio.sleep(0.05)
    assert await c.get(key) is None


@pytest.mark.asyncio
async def test_invalidate_session_only_clears_matching_sid() -> None:
    c = ShowResultCache()
    await c.set(("s1", "h", "show a"), {"x": 1}, ttl_seconds=5)
    await c.set(("s1", "h", "show b"), {"x": 2}, ttl_seconds=5)
    await c.set(("s2", "h", "show a"), {"x": 3}, ttl_seconds=5)
    await c.invalidate_session("s1")
    assert await c.get(("s1", "h", "show a")) is None
    assert await c.get(("s1", "h", "show b")) is None
    assert await c.get(("s2", "h", "show a")) == {"x": 3}


@pytest.mark.asyncio
async def test_tier_ttl_overrides() -> None:
    c = ShowResultCache()
    assert c.ttl_for_tier("static") == 120.0
    assert c.ttl_for_tier("near_realtime") == 15.0
    assert c.ttl_for_tier("realtime") == 0.0
    c.configure_tier_ttl("static", 30.0)
    assert c.ttl_for_tier("static") == 30.0


@pytest.mark.asyncio
async def test_configure_default_ttl_updates_near_realtime() -> None:
    c = ShowResultCache()
    c.configure_default_ttl(42.0)
    assert c.ttl_for_tier(None) == 42.0
    assert c.ttl_for_tier("near_realtime") == 42.0


@pytest.mark.asyncio
async def test_size_reflects_active_entries() -> None:
    c = ShowResultCache()
    assert await c.size() == 0
    await c.set(("s", "h", "c1"), {}, ttl_seconds=5)
    await c.set(("s", "h", "c2"), {}, ttl_seconds=5)
    assert await c.size() == 2
