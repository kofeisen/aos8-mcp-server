"""Integration-flavored tests for the aos8_log tool.

We don't talk to a real controller — instead we install a fake session in the
shared store and capture the final CLI string that would be sent. This makes
it easy to assert that ``tail`` / ``match`` / ``cli_suffix`` are composed in
the expected order without touching the network.
"""

from __future__ import annotations

from typing import Any

import pytest

from aos8_mcp import server


@pytest.mark.parametrize(
    ("command", "expected_tail"),
    [
        ("show log all", server._MAX_LOG_TAIL),
        ("show log all | include auth", server._MAX_LOG_TAIL),
        ("show log all 200 | include auth", 200),
        ("show log security all | include auth", None),
    ],
)
def test_apply_log_all_tail_if_needed(command: str, expected_tail: int | None) -> None:
    out, applied, auto, _capped = server._apply_log_all_tail_if_needed(command)
    if expected_tail is None:
        assert out == command
        assert applied is None
        assert auto is False
    else:
        assert f"show log all {expected_tail}" in out
        assert applied == expected_tail
        if "show log all |" in command:
            assert auto is True


@pytest.mark.parametrize(
    ("command", "tail", "include_rotated", "expected"),
    [
        ("show log errorlog", 100, None, "show log errorlog 100"),
        ("show log errorlog", 100, True, "show log errorlog 100"),
        ("show log errorlog", None, None, "show log errorlog all"),
        ("show log errorlog", None, False, "show log errorlog"),
        ("show log errorlog all", 100, None, "show log errorlog 100"),
        ("show log all", 50, None, "show log all 50"),
        (
            "show log all",
            None,
            True,
            f"show log all {server._MAX_LOG_TAIL}",
        ),
    ],
)
def test_compose_log_show_command_cli_bank_order(
    command: str,
    tail: int | None,
    include_rotated: bool | None,
    expected: str,
) -> None:
    assert (
        server._compose_log_show_command(
            command, tail=tail, include_rotated=include_rotated
        )
        == expected
    )


@pytest.fixture()
def fake_session(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``store.get`` and ``store.show_with_mm_then_md_fallback``.

    Returns a dict that captures the last command issued so each test can
    assert on it directly.
    """
    captured: dict[str, Any] = {"command": None}

    class _FakeSess:
        md_ips: list[str] = []

        def touch(self) -> None:  # pragma: no cover - unused but mirrors API
            return None

    async def fake_get(session_id: str) -> _FakeSess:
        if session_id != "sid-1":
            raise KeyError(f"Unknown session_id {session_id!r}; create a session first.")
        return _FakeSess()

    async def fake_show(
        session_id: str,
        command: str,
        *,
        use_cache: bool,
        cache_tier: str | None = None,
    ) -> dict[str, Any]:
        captured["command"] = command
        captured["use_cache"] = use_cache
        captured["cache_tier"] = cache_tier
        return {
            "target_host": "mm.example",
            "command": command,
            "http_status": 200,
            "raw": {"_format": "text", "_raw_text": "line1\nline2\nline3\n"},
            "executed_on": "mm",
            "md_ip_used": None,
            "conductor_rejected": False,
            "from_cache": False,
        }

    monkeypatch.setattr(server.store, "get", fake_get)
    monkeypatch.setattr(
        server.store,
        "show_with_mm_then_md_fallback",
        fake_show,
    )
    return captured


@pytest.mark.asyncio
async def test_variant_all_defaults_to_max_tail(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(session_id="sid-1", variant="all")
    assert out["ok"] is True
    assert fake_session["command"] == f"show log all {server._MAX_LOG_TAIL}"
    assert out.get("log_all_tail_auto_applied") is True


@pytest.mark.asyncio
async def test_basic_variant_runs_expected_command(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(session_id="sid-1", variant="security")
    assert out["ok"] is True
    assert fake_session["command"] == "show log security all"
    assert out["variant"] == "security"
    assert out["domain"] == "log"


@pytest.mark.asyncio
async def test_tail_is_appended_to_command(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(
        session_id="sid-1", variant="errorlog", tail=50
    )
    assert out["ok"] is True
    assert fake_session["command"] == "show log errorlog 50"
    assert out["tail_applied"] == 50
    assert "tail_capped" not in out


@pytest.mark.asyncio
async def test_tail_ignores_include_rotated(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(
        session_id="sid-1", variant="errorlog", tail=100, include_rotated=True
    )
    assert out["ok"] is True
    assert fake_session["command"] == "show log errorlog 100"


@pytest.mark.asyncio
async def test_tail_above_max_is_capped_for_cli(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(
        session_id="sid-1", variant="errorlog", tail=5000
    )
    assert out["ok"] is True
    assert fake_session["command"] == f"show log errorlog {server._MAX_LOG_TAIL}"
    assert out["tail_requested"] == 5000
    assert out["tail_applied"] == server._MAX_LOG_TAIL
    assert out["tail_capped"] is True


@pytest.mark.asyncio
async def test_match_becomes_include_pipe(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(
        session_id="sid-1", variant="user", match="auth"
    )
    assert out["ok"] is True
    assert fake_session["command"] == "show log user all | include auth"


@pytest.mark.asyncio
async def test_tail_and_match_combine_with_tail_before_pipe(
    fake_session: dict[str, Any],
) -> None:
    """``tail`` is mutually exclusive with ``all``; pipe filter follows the show clause."""
    out = await server.aos8_log(
        session_id="sid-1",
        variant="security",
        tail=5000,
        match="auth",
    )
    assert out["ok"] is True
    assert (
        fake_session["command"]
        == f"show log security {server._MAX_LOG_TAIL} | include auth"
    )
    assert out["tail_requested"] == 5000
    assert out["tail_capped"] is True


@pytest.mark.asyncio
async def test_match_strips_pipe_chars_to_avoid_injection(
    fake_session: dict[str, Any],
) -> None:
    out = await server.aos8_log(
        session_id="sid-1", variant="user", match="foo|bar"
    )
    assert out["ok"] is True
    assert fake_session["command"] == "show log user all | include foobar"


@pytest.mark.asyncio
async def test_match_only_pipes_is_rejected(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(session_id="sid-1", variant="user", match="||")
    assert out["ok"] is False
    assert "match" in out["error"]


@pytest.mark.asyncio
async def test_tail_zero_or_negative_is_rejected(fake_session: dict[str, Any]) -> None:
    out_zero = await server.aos8_log(session_id="sid-1", variant="user", tail=0)
    assert out_zero["ok"] is False
    out_neg = await server.aos8_log(session_id="sid-1", variant="user", tail=-5)
    assert out_neg["ok"] is False


@pytest.mark.asyncio
async def test_hyphenated_variant_alias_resolves(fake_session: dict[str, Any]) -> None:
    """Users can pass the official hyphenated category name."""
    out = await server.aos8_log(session_id="sid-1", variant="peer-debug", tail=10)
    assert out["ok"] is True
    assert fake_session["command"] == "show log peer-debug 10"
    assert out["variant"] == "peer_debug"


@pytest.mark.asyncio
async def test_user_cli_suffix_combines_after_match(
    fake_session: dict[str, Any],
) -> None:
    out = await server.aos8_log(
        session_id="sid-1",
        variant="all",
        match="auth",
        cli_suffix="| exclude debug",
    )
    assert out["ok"] is True
    assert (
        fake_session["command"]
        == f"show log all {server._MAX_LOG_TAIL} | include auth | exclude debug"
    )
    assert out.get("log_all_tail_auto_applied") is True


@pytest.mark.asyncio
async def test_command_override_show_log_all_include_gets_tail_cap(
    fake_session: dict[str, Any],
) -> None:
    out = await server.aos8_log(
        session_id="sid-1",
        command_override="show log all | include auth",
    )
    assert out["ok"] is True
    assert fake_session["command"] == f"show log all {server._MAX_LOG_TAIL} | include auth"
    assert out.get("log_all_tail_auto_applied") is True


@pytest.mark.asyncio
async def test_command_override_bypasses_preset(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(
        session_id="sid-1",
        command_override="show log security",
        tail=10,
    )
    assert out["ok"] is True
    assert fake_session["command"] == "show log security 10"
    assert "variant" not in out


@pytest.mark.asyncio
async def test_tail_raises_max_lines_when_explicit_max_is_lower(
    fake_session: dict[str, Any],
) -> None:
    """Device tail above max_lines bumps the server-side cap to match."""
    out = await server.aos8_log(
        session_id="sid-1", variant="user", tail=100, max_lines=50
    )
    assert out["ok"] is True
    assert fake_session["command"] == "show log user 100"
    assert out["tail_applied"] == 100


@pytest.mark.asyncio
async def test_log_target_md_uses_show_on_target(
    fake_session: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_fetch_log_show(
        session_id: str,
        command: str,
        *,
        target: str,
        md_ip: str | None,
        use_cache: bool,
        cache_tier: str | None,
    ) -> dict[str, Any]:
        calls.append(
            {
                "session_id": session_id,
                "command": command,
                "target": target,
                "md_ip": md_ip,
            }
        )
        return {
            "target_host": md_ip,
            "command": command,
            "http_status": 200,
            "raw": {"_format": "text", "_raw_text": "May 16 22:00:00  test: hello\n"},
            "executed_on": "md",
            "md_ip_used": md_ip,
            "from_cache": False,
        }

    monkeypatch.setattr(server, "_fetch_log_show", fake_fetch_log_show)

    out = await server.aos8_log(
        session_id="sid-1",
        variant="errorlog",
        tail=50,
        target="md",
        md_ip="10.0.10.16",
    )
    assert out["ok"] is True
    assert calls == [
        {
            "session_id": "sid-1",
            "command": "show log errorlog 50",
            "target": "md",
            "md_ip": "10.0.10.16",
        }
    ]
    assert out["target_host"] == "10.0.10.16"
    assert out["executed_on"] == "md"


@pytest.mark.asyncio
async def test_log_target_md_requires_md_ip(fake_session: dict[str, Any]) -> None:
    out = await server.aos8_log(
        session_id="sid-1", variant="security", tail=10, target="md"
    )
    assert out["ok"] is False
    assert "md_ip" in out["error"].lower()


@pytest.mark.asyncio
async def test_log_read_timeout_returns_structured_error(
    fake_session: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from aos8_mcp.aruba_client import ArubaHttpError

    async def fake_show_on_target(
        session_id: str,
        command: str,
        *,
        target: str,
        md_ip: str | None,
        use_cache: bool,
        cache_tier: str | None = None,
    ) -> dict[str, Any]:
        raise ArubaHttpError(
            "Timed out waiting for show command response from 10.128.2.11 "
            "(read timeout 120s)."
        )

    monkeypatch.setattr(server.store, "show_on_target", fake_show_on_target)

    out = await server.aos8_log(
        session_id="sid-1",
        variant="system",
        tail=30,
        target="md",
        md_ip="10.128.2.11",
    )
    assert out == {
        "ok": False,
        "error": (
            "Timed out waiting for show command response from 10.128.2.11 "
            "(read timeout 120s)."
        ),
    }


@pytest.mark.asyncio
async def test_log_target_md_rejects_ip_not_in_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSess:
        md_ips = ["10.0.10.16"]

        def touch(self) -> None:
            return None

    async def fake_get(session_id: str) -> _FakeSess:
        if session_id != "sid-1":
            raise KeyError(f"Unknown session_id {session_id!r}; create a session first.")
        return _FakeSess()

    monkeypatch.setattr(server.store, "get", fake_get)

    out = await server.aos8_log(
        session_id="sid-1",
        variant="system",
        tail=30,
        target="md",
        md_ip="10.128.2.11",
    )
    assert out["ok"] is False
    assert "10.128.2.11" in out["error"]
    assert "configured MD list" in out["error"]


@pytest.mark.asyncio
async def test_aos8_show_log_all_include_gets_tail_cap(
    fake_session: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_show_on_target(
        session_id: str,
        command: str,
        *,
        target: str,
        md_ip: str | None,
        use_cache: bool,
        cache_tier: str | None = None,
    ) -> dict[str, Any]:
        fake_session["command"] = command
        return {
            "target_host": "mm.example",
            "command": command,
            "http_status": 200,
            "raw": {"_format": "text", "_raw_text": "line1\n"},
            "executed_on": "mm",
            "md_ip_used": None,
            "from_cache": False,
        }

    monkeypatch.setattr(server.store, "show_on_target", fake_show_on_target)

    out = await server.aos8_show(
        session_id="sid-1",
        command="show log all | include auth",
    )
    assert out["ok"] is True
    assert fake_session["command"] == f"show log all {server._MAX_LOG_TAIL} | include auth"
    assert out.get("log_all_tail_auto_applied") is True


@pytest.mark.asyncio
async def test_unknown_session_returns_clean_error() -> None:
    """Without the fixture, store.get raises KeyError -> propagated as error."""
    out = await server.aos8_log(session_id="missing", variant="all")
    assert out["ok"] is False
    assert "session" in out["error"].lower() or "unknown" in out["error"].lower()
