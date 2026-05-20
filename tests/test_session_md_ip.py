"""Tests for MD target validation on show execution."""

from __future__ import annotations

import pytest

from aos8_mcp.session_store import Aos8ServerSession, SessionStore, _validate_session_md_ip


def test_validate_session_md_ip_rejects_unknown() -> None:
    sess = Aos8ServerSession(
        session_id="sid",
        mm_host="10.0.50.11",
        username="demo",
        password="secret",
        verify_ssl=False,
        md_ips=["10.0.10.16", "10.128.2.11"],
    )
    with pytest.raises(ValueError, match="10.9.9.9"):
        _validate_session_md_ip(sess, "10.9.9.9")
    _validate_session_md_ip(sess, "10.128.2.11")


def test_validate_session_md_ip_allows_any_when_list_empty() -> None:
    sess = Aos8ServerSession(
        session_id="sid",
        mm_host="10.0.50.11",
        username="demo",
        password="secret",
        verify_ssl=False,
        md_ips=[],
    )
    _validate_session_md_ip(sess, "10.9.9.9")


@pytest.mark.asyncio
async def test_show_on_target_rejects_md_ip_not_in_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionStore()
    sess = Aos8ServerSession(
        session_id="sid-1",
        mm_host="10.0.50.11",
        username="demo",
        password="secret",
        verify_ssl=False,
        md_ips=["10.0.10.16"],
    )

    async def fake_get(session_id: str) -> Aos8ServerSession:
        assert session_id == "sid-1"
        return sess

    monkeypatch.setattr(store, "get", fake_get)

    with pytest.raises(ValueError, match="10.128.2.11"):
        await store.show_on_target(
            "sid-1",
            "show log system 30",
            target="md",
            md_ip="10.128.2.11",
            use_cache=False,
        )
