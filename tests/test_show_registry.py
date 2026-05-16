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
        "airmatch",
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
        ("controllers", "switches_all", "show switches all"),
        ("controllers", "switches_debug", "show switches debug"),
        ("controllers", "switches_regulatory", "show switches regulatory"),
        ("controllers", "switches_summary", "show switches summary"),
        ("controllers", "switches_state_complete", "show switches state complete"),
        ("controllers", "switches_state_inprogress", "show switches state inprogress"),
        ("controllers", "switches_state_required", "show switches state required"),
        ("system", "switchinfo", "show switchinfo"),
        ("system", "switch_software", "show switch software"),
        ("system", "switch_ip", "show switch ip"),
        ("clients", "user_table", "show user-table"),
        ("clients", "user", "show user"),
        ("clients", "user_table_summary", "show user-table summary"),
        ("clients", "user_table_unique", "show user-table unique"),
        ("clients", "global_user_table_list", "show global-user-table list"),
        ("aps", "database", "show ap database"),
        ("wlan", "virtual_ap", "show wlan virtual-ap"),
        ("wlan", "wlan_profiles", "show wlan"),
        ("system", "license_summary", "show license summary"),
        ("network", "ip_route", "show ip route"),
        ("aaa", "authentication_server_all", "show aaa authentication-server all"),
        ("aaa", "authentication_dot1x_countermeasures", "show aaa authentication dot1x countermeasures"),
        ("aaa", "authentication_stateful_dot1x", "show aaa authentication stateful-dot1x"),
        (
            "aaa",
            "authentication_stateful_dot1x_config_entries",
            "show aaa authentication stateful-dot1x config-entries",
        ),
        ("aaa", "authentication_server_radius", "show aaa authentication-server radius"),
        (
            "aaa",
            "authentication_server_radius_statistics",
            "show aaa authentication-server radius statistics",
        ),
        (
            "aaa",
            "authentication_server_radius_radsec_status",
            "show aaa authentication-server radius radsec status",
        ),
        ("cluster", "lc_cluster_group_membership", "show lc-cluster group-membership"),
        ("cluster", "lc_cluster_heartbeat_counters", "show lc-cluster heartbeat counters"),
        ("cluster", "lc_cluster_load_distribution_ap", "show lc-cluster load distribution ap"),
        ("cluster", "lc_cluster_history", "show lc-cluster history"),
        ("cluster", "lc_cluster_vlan_probe_status", "show lc-cluster vlan-probe status"),
        ("cluster", "datapath_cluster", "show datapath cluster"),
        ("cluster", "datapath_cluster_details", "show datapath cluster details"),
        ("rf", "arm_rf_summary", "show ap arm rf-summary"),
        ("rf", "rf_arm_profile", "show rf arm-profile"),
        ("rf", "rf_spectrum_profile", "show rf spectrum-profile"),
        ("rf", "rf_dot11a_radio_profile", "show rf dot11a-radio-profile"),
        ("log", "errorlog", "show log errorlog"),
        ("log", "ap_debug", "show log ap-debug"),
        ("log", "arm_user_debug", "show log arm-user-debug"),
        ("log", "network", "show log network"),
        ("log", "peer_debug", "show log peer-debug"),
        ("log", "user_debug", "show log user-debug"),
        ("datapath", "tunnel", "show datapath tunnel"),
        ("datapath", "tunnel_counters", "show datapath tunnel counters"),
        ("datapath", "bridge", "show datapath bridge"),
        ("datapath", "utilization", "show datapath utilization"),
        ("datapath", "session_session_id", "show datapath session session-id"),
        ("datapath", "vlan_table", "show datapath vlan table"),
        ("airmatch", "optimization", "show airmatch optimization"),
        ("airmatch", "solution_list_all", "show airmatch solution list-all"),
        ("airmatch", "debug_db_dump_status", "show airmatch debug db-dump status"),
        ("airmatch", "debug_optimization", "show airmatch debug optimization"),
    ],
)
def test_known_presets_have_expected_commands(
    domain: str, variant: str, expected_cmd: str
) -> None:
    assert resolve_preset(domain, variant).command == expected_cmd


def test_aaa_aliases_resolve_to_canonical_keys() -> None:
    assert resolve_preset("aaa", "auth_servers").key == "authentication_server_all"
    assert resolve_preset("aaa", "radius").key == "authentication_server_radius"
    assert resolve_preset("aaa", "radius_statistics").key == "authentication_server_radius_statistics"
    assert resolve_preset("aaa", "radius_radsec").key == "authentication_server_radius_radsec_status"
    assert resolve_preset("aaa", "dot1x").key == "authentication_dot1x"
    assert resolve_preset("aaa", "cp").key == "authentication_captive_portal"
    assert resolve_preset("aaa", "stateful_dot1x_config").key == (
        "authentication_stateful_dot1x_config_entries"
    )


def test_cluster_aliases_resolve_to_canonical_keys() -> None:
    assert resolve_preset("cluster", "group_membership").key == "lc_cluster_group_membership"
    assert resolve_preset("cluster", "heartbeat_counters").key == "lc_cluster_heartbeat_counters"
    assert resolve_preset("cluster", "load_ap").key == "lc_cluster_load_distribution_ap"
    assert resolve_preset("cluster", "load_client").key == "lc_cluster_load_distribution_client"
    assert resolve_preset("cluster", "bucket_essid").key == "lc_cluster_bucket_distribution_essid"
    assert resolve_preset("cluster", "dp_cluster_details").key == "datapath_cluster_details"


def test_wlan_aliases_resolve_to_canonical_keys() -> None:
    assert resolve_preset("wlan", "vap").key == "virtual_ap"
    assert resolve_preset("wlan", "ssid").key == "ssid_profile"
    assert resolve_preset("wlan", "profiles").key == "wlan_profiles"
    assert resolve_preset("wlan", "wmm_tm").key == "wmm_traffic_management_profile"


def test_clients_aliases_resolve_to_canonical_keys() -> None:
    assert resolve_preset("clients", "global").key == "global_user_table_list"
    assert resolve_preset("clients", "ut").key == "user_table"
    assert resolve_preset("clients", "table_summary").key == "user_table_summary"


def test_controllers_short_aliases_resolve_to_canonical_keys() -> None:
    for short, expected in (
        ("all", "switches_all"),
        ("debug", "switches_debug"),
        ("regulatory", "switches_regulatory"),
        ("summary", "switches_summary"),
        ("state_down", "switches_state_down"),
        ("state_inprogress", "switches_state_inprogress"),
        ("state_required", "switches_state_required"),
    ):
        assert resolve_preset("controllers", short).key == expected


def test_system_local_box_presets_use_correct_commands() -> None:
    """switchinfo / switch_software / switch_ip should be reachable via aos8_system."""
    assert resolve_preset("system", "switchinfo").command == "show switchinfo"
    assert resolve_preset("system", "switch_software").command == "show switch software"
    assert resolve_preset("system", "switch_ip").command == "show switch ip"


def test_airmatch_aliases_resolve() -> None:
    assert resolve_preset("airmatch", "opt").key == "optimization"
    assert resolve_preset("airmatch", "solution_all").key == "solution_list_all"
    assert resolve_preset("airmatch", "partition").key == "ap_partition_status_detail"
    assert resolve_preset("airmatch", "dbg_opt").key == "debug_optimization"


def test_every_airmatch_preset_starts_with_show_airmatch() -> None:
    from aos8_mcp.show_registry import AIRMATCH_PRESETS

    for key, preset in AIRMATCH_PRESETS.items():
        assert preset.command.startswith("show airmatch "), (
            f"{key}: expected 'show airmatch …', got {preset.command!r}"
        )


def test_rf_hyphenated_doc_names_resolve_via_aliases() -> None:
    """CLI-Bank lists hyphenated parameter names; normalize_key + aliases map them."""
    assert resolve_preset("rf", "arm-profile").key == "rf_arm_profile"
    assert resolve_preset("rf", "spectrum-profile").key == "rf_spectrum_profile"
    assert resolve_preset("rf", "arm_profile").key == "rf_arm_profile"


def test_rf_summary_alias_points_to_arm_rf_summary() -> None:
    assert resolve_preset("rf", "rf_summary").key == "arm_rf_summary"


def test_every_show_rf_preset_has_correct_prefix() -> None:
    from aos8_mcp.show_registry import RF_PRESETS

    for key, preset in RF_PRESETS.items():
        if not key.startswith("rf_"):
            continue
        assert preset.command.startswith("show rf "), (
            f"{key} expected 'show rf …', got {preset.command!r}"
        )


def test_hyphenated_log_variant_names_resolve_via_normalize_key() -> None:
    """Users should be able to pass the official hyphenated category name."""
    for hyphen, expected_key in (
        ("ap-debug", "ap_debug"),
        ("arm-user-debug", "arm_user_debug"),
        ("peer-debug", "peer_debug"),
        ("user-debug", "user_debug"),
    ):
        assert resolve_preset("log", hyphen).key == expected_key


def test_every_log_preset_runs_show_log_command_and_is_realtime() -> None:
    """Sanity-check that every log preset is well-formed."""
    from aos8_mcp.show_registry import LOG_PRESETS

    for key, preset in LOG_PRESETS.items():
        assert preset.command.startswith("show log "), (
            f"{key} does not start with 'show log ': {preset.command!r}"
        )
        assert preset.normalizer == "log_text"
        assert preset.cache_tier == "realtime"


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
    assert resolve_preset("datapath", "cpu").key == "utilization"
    assert resolve_preset("datapath", "cpu_utilization").key == "utilization"


def test_every_datapath_preset_runs_show_datapath_command() -> None:
    for key, preset in DATAPATH_PRESETS.items():
        assert preset.command.startswith("show datapath "), (
            f"{key} command does not start with 'show datapath ': {preset.command!r}"
        )
        assert preset.cache_tier == "realtime", (
            f"{key} cache_tier should be 'realtime' (forwarding state changes constantly)"
        )
