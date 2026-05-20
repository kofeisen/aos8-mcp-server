"""Tests for Aruba HTTP client auth heuristics."""

from __future__ import annotations

import httpx
import pytest

from aos8_mcp.aruba_client import (
    ArubaAuthExpired,
    ArubaDeviceClient,
    ArubaHttpError,
    _looks_like_auth_failure,
    build_http_timeout,
    configured_http_connect_timeout_seconds,
    configured_http_read_timeout_seconds,
    format_transport_error,
)


def test_log_xml_payload_is_not_auth_failure() -> None:
    payload = {
        "_format": "log_xml_wrapper",
        "lines": [
            "May 16 22:00:00  authmgr: Mgmt User Authentication failed. userip=1.2.3.4",
        ],
    }
    assert _looks_like_auth_failure(200, payload) is False


def test_global_result_error_is_auth_failure() -> None:
    payload = {
        "_global_result": {"status": "1", "status_str": "You must authenticate yourself"},
    }
    assert _looks_like_auth_failure(200, payload) is True


def test_multiline_log_text_is_not_auth_failure() -> None:
    payload = {
        "_format": "text",
        "_raw_text": "line1 authentication failed\nline2\nline3\n",
    }
    assert _looks_like_auth_failure(200, payload) is False


@pytest.mark.asyncio
async def test_show_command_does_not_raise_on_log_with_auth_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: MD log lines must not trigger ArubaAuthExpired + spurious relogin."""

    class _FakeResp:
        status_code = 200
        text = (
            '<my_xml_tag _template="log">'
            "May 16 22:00:00  authmgr: Mgmt User Authentication failed\n"
            "</my_xml_tag>"
        )

    async def fake_get(*_a: object, **_k: object) -> _FakeResp:
        return _FakeResp()

    client = ArubaDeviceClient("10.0.10.16", verify_ssl=False)
    client.tokens = type("T", (), {"uidaruba": "u", "csrf": "c"})()  # type: ignore[assignment]
    client._username = "user"
    client._password = "pass"
    monkeypatch.setattr(client._client, "get", fake_get)

    status, parsed = await client.show_command("show log all 50")
    assert status == 200
    assert parsed.get("_format") == "log_xml_wrapper"
    assert "Authentication failed" in parsed["lines"][0]


def test_format_transport_error_read_timeout() -> None:
    msg = format_transport_error(
        "10.128.2.11",
        httpx.ReadTimeout("timed out"),
        operation="show command",
    )
    assert "10.128.2.11" in msg
    assert "read timeout" in msg
    assert str(int(configured_http_read_timeout_seconds())) in msg


def test_build_http_timeout_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AOS8_HTTP_READ_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("AOS8_HTTP_CONNECT_TIMEOUT_SECONDS", "12")
    t = build_http_timeout()
    assert t.read == 45.0
    assert t.connect == 12.0


@pytest.mark.asyncio
async def test_show_command_wraps_read_timeout_as_aruba_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(*_a: object, **_k: object) -> None:
        raise httpx.ReadTimeout("timed out")

    client = ArubaDeviceClient("10.128.2.11", verify_ssl=False)
    client.tokens = type("T", (), {"uidaruba": "u", "csrf": "c"})()  # type: ignore[assignment]
    monkeypatch.setattr(client._client, "get", fake_get)

    with pytest.raises(ArubaHttpError, match="read timeout"):
        await client.show_command("show log system 30")
