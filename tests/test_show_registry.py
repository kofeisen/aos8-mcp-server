"""Tests for the show preset registry."""

from __future__ import annotations

import pytest

from aos8_mcp.show_registry import (
    AP_PRESETS,
    DATAPATH_PRESETS,
    DOMAINS,
    domain_catalog,
    full_catalog,
    get_domain,
    normalize_key,
    resolve_preset,
)


def test_normalize_key_lowercases_and_substitutes_dashes() -> None:
    assert normalize_key("Ap-Database") == "ap_database"
    assert normalize_key("  IP-INTERFACE-BRIEF  ") == "ip_interface_brief"


def test_all_expected_domains_present() -> None:
    expected = {
        "controllers",
        "clients",
        "aps",
        "wlan",
        "log",
        "system",
        "network",
        "aaa",
        "cluster",
        "rf",
        "datapath",
    }
    assert expected.issubset(DOMAINS.keys())


def test_default_variants_resolve_for_every_domain() -> None:
    for name, spec in DOMAINS.items():
        preset = resolve_preset(name, None)
        assert preset.key == spec.default_variant, f"{name} default mismatch"
        assert preset.command.startswith("show ")


def test_unknown_domain_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_domain("nope")
    with pytest.raises(KeyError):
        resolve_preset("nope", "anything")


def test_unknown_variant_raises_value_error() -> None:
    with pytest.raises(ValueError):
        resolve_preset("aps", "does_not_exist")


def test_ap_alias_global_maps_to_ap_global() -> None:
    preset = resolve_preset("aps", "global")
    assert preset.key == "ap_global"
    assert preset.command == "show ap global"


def test_legacy_blacklist_variants_removed() -> None:
    for legacy in (
        "blacklist_clients",
        "blacklist_protected",
        "blacklist_time",
    ):
        assert legacy not in AP_PRESETS, f"{legacy} should have been dropped"


def test_wlan_ssid_profile_marks_profile_required() -> None:
    preset = resolve_preset("wlan", "ssid_profile")
    assert preset.needs_profile_name is True
    assert preset.profile_name_default == "default"


def test_domain_catalog_entries_are_serializable() -> None:
    cat = domain_catalog("system")
    assert "version" in cat
    entry = cat["version"]
    assert entry["command"] == "show version"
    assert entry["cache_tier"] in {"static", "near_realtime", "realtime"}
    assert entry["normalizer"]
    assert entry["description"]


def test_full_catalog_contains_meta_and_variants() -> None:
    cat = full_catalog()
    assert set(cat.keys()) == set(DOMAINS.keys())
    for name, payload in cat.items():
        assert "meta" in payload and "variants" in payload
        assert payload["meta"]["default_variant"]
        assert payload["variants"], f"{name} has no variants"


@pytest.mark.parametrize(
    ("domain", "variant", "expected_cmd"),
    [
        ("controllers", "switches", "show switches"),
        ("clients", "global_user_table_list", "show global-user-table list"),
        ("aps", "database", "show ap database"),
        ("wlan", "virtual_ap", "show wlan virtual-ap"),
        ("system", "license_summary", "show license summary"),
        ("network", "ip_route", "show ip route"),
        ("aaa", "authentication_server_all", "show aaa authentication-server all"),
        ("cluster", "lc_cluster_group_membership", "show lc-cluster group-membership"),
        ("cluster", "lc_cluster_heartbeat_counters", "show lc-cluster heartbeat counters"),
        ("cluster", "lc_cluster_load_distribution_ap", "show lc-cluster load distribution ap"),
        ("cluster", "lc_cluster_history", "show lc-cluster history"),
        ("cluster", "lc_cluster_vlan_probe_status", "show lc-cluster vlan-probe status"),
        ("cluster", "datapath_cluster", "show datapath cluster"),
        ("cluster", "datapath_cluster_details", "show datapath cluster details"),
        ("rf", "arm_rf_summary", "show ap arm rf-summary"),
        ("log", "errorlog", "show log errorlog all"),
        ("datapath", "tunnel", "show datapath tunnel"),
        ("datapath", "tunnel_counters", "show datapath tunnel counters"),
        ("datapath", "bridge", "show datapath bridge"),
        ("datapath", "session_session_id", "show datapath session session-id"),
        ("datapath", "vlan_table", "show datapath vlan table"),
    ],
)
def test_known_presets_have_expected_commands(
    domain: str, variant: str, expected_cmd: str
) -> None:
    assert resolve_preset(domain, variant).command == expected_cmd


def test_cluster_aliases_resolve_to_canonical_keys() -> None:
    assert resolve_preset("cluster", "group_membership").key == "lc_cluster_group_membership"
    assert resolve_preset("cluster", "heartbeat_counters").key == "lc_cluster_heartbeat_counters"
    assert resolve_preset("cluster", "load_ap").key == "lc_cluster_load_distribution_ap"
    assert resolve_preset("cluster", "load_client").key == "lc_cluster_load_distribution_client"
    assert resolve_preset("cluster", "bucket_essid").key == "lc_cluster_bucket_distribution_essid"
    assert resolve_preset("cluster", "dp_cluster_details").key == "datapath_cluster_details"


def test_every_lc_cluster_preset_uses_lc_cluster_command() -> None:
    """All ``lc_cluster_*`` presets must invoke ``show lc-cluster ...``."""
    from aos8_mcp.show_registry import CLUSTER_PRESETS

    for key, preset in CLUSTER_PRESETS.items():
        if not key.startswith("lc_cluster_"):
            continue
        assert preset.command.startswith("show lc-cluster "), (
            f"{key} does not start with 'show lc-cluster ': {preset.command!r}"
        )


def test_datapath_default_variant_is_tunnel() -> None:
    assert get_domain("datapath").default_variant == "tunnel"
    assert resolve_preset("datapath", None).command == "show datapath tunnel"


def test_datapath_aliases_resolve_to_singular_forms() -> None:
    assert resolve_preset("datapath", "tunnels").key == "tunnel"
    assert resolve_preset("datapath", "sessions").key == "session"
    assert resolve_preset("datapath", "users").key == "user"
    assert resolve_preset("datapath", "vlans").key == "vlan"


def test_every_datapath_preset_runs_show_datapath_command() -> None:
    for key, preset in DATAPATH_PRESETS.items():
        assert preset.command.startswith("show datapath "), (
            f"{key} command does not start with 'show datapath ': {preset.command!r}"
        )
        assert preset.cache_tier == "realtime", (
            f"{key} cache_tier should be 'realtime' (forwarding state changes constantly)"
        )
