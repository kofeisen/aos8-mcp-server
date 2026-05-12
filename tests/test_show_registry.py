"""Tests for the show preset registry."""

from __future__ import annotations

import pytest

from aos8_mcp.show_registry import (
    AP_PRESETS,
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
        ("rf", "arm_rf_summary", "show ap arm rf-summary"),
        ("log", "errorlog", "show log errorlog all"),
    ],
)
def test_known_presets_have_expected_commands(
    domain: str, variant: str, expected_cmd: str
) -> None:
    assert resolve_preset(domain, variant).command == expected_cmd
