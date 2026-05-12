"""Tests for the idle-session reaper. Uses fake sessions to avoid network I/O."""

from __future__ import annotations

import time

import pytest

from aos8_mcp.session_store import Aos8ServerSession, SessionStore


def _fake_session(sid: str, *, last_activity: float) -> Aos8ServerSession:
    return Aos8ServerSession(
        session_id=sid,
        mm_host="10.0.0.1",
        username="admin",
        password="pw",
        verify_ssl=False,
        last_activity_monotonic=last_activity,
    )


@pytest.mark.asyncio
async def test_reap_once_disabled_returns_empty() -> None:
    store = SessionStore()
    store._sessions["s1"] = _fake_session("s1", last_activity=time.monotonic() - 999)
    assert await store._reap_once() == []
    assert "s1" in store._sessions


@pytest.mark.asyncio
async def test_reap_once_drops_only_stale_sessions() -> None:
    store = SessionStore()
    store.configure_idle_reap(idle_timeout_seconds=10, scan_interval_seconds=60)
    now = time.monotonic()
    store._sessions["fresh"] = _fake_session("fresh", last_activity=now - 1)
    store._sessions["stale"] = _fake_session("stale", last_activity=now - 30)
    reaped = await store._reap_once(now=now)
    assert reaped == ["stale"]
    assert "fresh" in store._sessions
    assert "stale" not in store._sessions


@pytest.mark.asyncio
async def test_describe_includes_idle_and_age() -> None:
    store = SessionStore()
    sess = _fake_session("sX", last_activity=time.monotonic() - 5)
    store._sessions["sX"] = sess
    info = await store.describe("sX")
    assert info["session_id"] == "sX"
    assert info["mm_host"] == "10.0.0.1"
    assert info["idle_seconds"] >= 5.0
    assert info["age_seconds"] >= 0.0


@pytest.mark.asyncio
async def test_touch_updates_last_activity() -> None:
    sess = _fake_session("t1", last_activity=time.monotonic() - 100)
    sess.touch()
    assert sess.idle_seconds() < 1.0


def test_configure_idle_reap_clamps_to_minimum_interval() -> None:
    store = SessionStore()
    store.configure_idle_reap(idle_timeout_seconds=600, scan_interval_seconds=0.1)
    assert store.reap_interval >= 1.0
    assert store.idle_timeout == 600
