"""Tests for ``aos8_airmatch`` command composition."""

from __future__ import annotations

from aos8_mcp import server


def test_compose_debug_history_inserts_ap_name() -> None:
    cmd = server._compose_airmatch_command(
        "debug_history",
        "show airmatch debug history",
        ap_name="West-2-155",
        arg=None,
    )
    assert cmd == "show airmatch debug history ap-name West-2-155"


def test_compose_optimization_appends_sequence_via_arg() -> None:
    cmd = server._compose_airmatch_command(
        "optimization",
        "show airmatch optimization",
        ap_name=None,
        arg="14",
    )
    assert cmd == "show airmatch optimization 14"


def test_compose_optimization_ignores_ap_name() -> None:
    cmd = server._compose_airmatch_command(
        "optimization",
        "show airmatch optimization",
        ap_name="ShouldNotAppear",
        arg="9",
    )
    assert cmd == "show airmatch optimization 9"


def test_compose_debug_optimization_advanced_partition() -> None:
    cmd = server._compose_airmatch_command(
        "debug_optimization",
        "show airmatch debug optimization",
        ap_name=None,
        arg="advanced partition",
    )
    assert cmd == "show airmatch debug optimization advanced partition"


def test_compose_solution_ap_name_then_arg_band() -> None:
    cmd = server._compose_airmatch_command(
        "solution",
        "show airmatch solution",
        ap_name="AP1",
        arg="band 5 GHz",
    )
    assert cmd == "show airmatch solution ap-name AP1 band 5 GHz"
