"""Tests for Aruba HTTP client auth heuristics."""

from __future__ import annotations

import pytest

from aos8_mcp.aruba_client import (
    ArubaAuthExpired,
    ArubaDeviceClient,
    _looks_like_auth_failure,
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
