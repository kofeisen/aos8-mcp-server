"""Tests for ``aos8_aaa`` trailing-token composition."""

from __future__ import annotations

from aos8_mcp import server


def test_aaa_extra_cli_appends_optional_profile_for_dot1x_family() -> None:
    assert (
        server._compose_aaa_extra_cli(
            "authentication_dot1x",
            profile_name="pDot1x",
            arg=None,
        )
        == "pDot1x"
    )


def test_aaa_extra_cli_profile_then_arg_for_mac() -> None:
    assert (
        server._compose_aaa_extra_cli(
            "authentication_mac",
            profile_name="macprof",
            arg="ignored_second",
        )
        == "macprof ignored_second"
    )


def test_aaa_extra_cli_ignores_profile_for_radius_list_preset() -> None:
    assert (
        server._compose_aaa_extra_cli(
            "authentication_server_radius",
            profile_name="should_not_apply",
            arg="rad1",
        )
        == "rad1"
    )


def test_aaa_extra_cli_arg_only_when_no_profile_preset() -> None:
    assert (
        server._compose_aaa_extra_cli(
            "state_messages",
            profile_name="x",
            arg="| include foo",
        )
        == "| include foo"
    )
