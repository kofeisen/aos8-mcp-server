"""Tests for the datapath / cluster command-composition helpers."""

from __future__ import annotations

import pytest

from aos8_mcp.server import _cluster_command_prefers_md, _compose_datapath_command


def test_no_extra_params_returns_base() -> None:
    assert _compose_datapath_command(
        "show datapath bridge", ap_name=None, ip_addr=None, arg=None
    ) == "show datapath bridge"


def test_ap_name_appends_keyword_token() -> None:
    assert _compose_datapath_command(
        "show datapath bridge", ap_name="AP-M020", ip_addr=None, arg=None
    ) == "show datapath bridge ap-name AP-M020"


def test_ip_addr_appends_keyword_token() -> None:
    assert _compose_datapath_command(
        "show datapath session", ap_name=None, ip_addr="10.1.1.1", arg=None
    ) == "show datapath session ip-addr 10.1.1.1"


def test_ap_name_skipped_when_base_already_has_keyword() -> None:
    """``bridge ap-name`` is its own preset already; do not duplicate the keyword."""
    assert _compose_datapath_command(
        "show datapath bridge ap-name", ap_name="AP-M020", ip_addr=None, arg=None
    ) == "show datapath bridge ap-name"


def test_arg_is_appended_verbatim_for_positional_values() -> None:
    assert _compose_datapath_command(
        "show datapath bridge table",
        ap_name=None,
        ip_addr=None,
        arg="aa:bb:cc:dd:ee:ff",
    ) == "show datapath bridge table aa:bb:cc:dd:ee:ff"


def test_tunnel_id_with_qualifier_via_arg() -> None:
    """Mimic ``show datapath tunnel tunnel-id 12 trusted-vlan``."""
    assert _compose_datapath_command(
        "show datapath tunnel tunnel-id",
        ap_name=None,
        ip_addr=None,
        arg="12 trusted-vlan",
    ) == "show datapath tunnel tunnel-id 12 trusted-vlan"


@pytest.mark.parametrize(
    ("ap_name", "ip_addr", "arg", "expected"),
    [
        ("AP-1", None, None, "show datapath user ap-name AP-1"),
        (None, "10.0.0.5", None, "show datapath user ip-addr 10.0.0.5"),
        ("AP-1", "10.0.0.5", None, "show datapath user ap-name AP-1 ip-addr 10.0.0.5"),
    ],
)
def test_user_variant_combinations(
    ap_name: str | None, ip_addr: str | None, arg: str | None, expected: str
) -> None:
    assert (
        _compose_datapath_command(
            "show datapath user", ap_name=ap_name, ip_addr=ip_addr, arg=arg
        )
        == expected
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("show lc-cluster group-membership", True),
        ("show lc-cluster heartbeat counters", True),
        ("SHOW LC-CLUSTER history", True),
        ("show datapath cluster", True),
        ("show datapath cluster details peer 10.1.1.1", True),
        ("show datapath cluster heartbeat counters", True),
        ("show datapath cluster details | include peer", True),
        ("show switches state", False),
        ("show heartbeat", False),
        ("show master-redundancy", False),
        ("show datapath tunnel", False),
        ("show datapath bridge counters", False),
    ],
)
def test_cluster_command_prefers_md(command: str, expected: bool) -> None:
    assert _cluster_command_prefers_md(command) is expected
