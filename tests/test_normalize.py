"""Tests for normalize_payload heuristics."""

from __future__ import annotations

import pytest

from aos8_mcp.normalize import normalize_payload


def test_generic_dict_lists_top_level_keys() -> None:
    out = normalize_payload("generic", {"a": 1, "b": 2, "_skip": 3})
    assert out == {"kind": "generic_json", "top_level_keys": ["a", "b"]}


def test_generic_list_returns_length() -> None:
    out = normalize_payload("generic", [1, 2, 3])
    assert out == {"kind": "generic_json_array", "length": 3}


def test_ap_database_extracts_known_key() -> None:
    payload = {"AP Database": [{"Name": "AP1"}, {"Name": "AP2"}]}
    out = normalize_payload("ap_database", payload)
    assert out["kind"] == "access_points"
    assert out["count"] == 2
    assert out["items"][0]["Name"] == "AP1"


def test_table_normalizer_falls_back_to_largest_list_of_dicts() -> None:
    """When the controller renames the header, we still pull the main rows."""
    payload = {"Some Renamed Header": [{"x": 1}, {"x": 2}, {"x": 3}]}
    out = normalize_payload("ap_database", payload)
    assert out["kind"] == "access_points"
    assert out["count"] == 3
    assert out["source_key"] == "Some Renamed Header"


def test_switches_normalizer_uses_all_switches_key() -> None:
    payload = {"All Switches": [{"IP": "1.1.1.1"}, {"IP": "1.1.1.2"}]}
    out = normalize_payload("switches", payload)
    assert out["kind"] == "switches"
    assert out["count"] == 2


def test_log_normalizer_log_xml_wrapper_shape() -> None:
    raw = {"_format": "log_xml_wrapper", "lines": [f"l{i}" for i in range(60)]}
    out = normalize_payload("log_text", raw)
    assert out["kind"] == "log"
    assert out["line_count"] == 60
    assert out["summary"]["total_lines"] == 60
    assert "head" not in out


def test_log_normalizer_text_format() -> None:
    raw = {"_format": "text", "_raw_text": "a\nb\nc\n"}
    out = normalize_payload("log_text", raw)
    assert out["kind"] == "log"
    assert out["line_count"] == 3
    assert out["summary"]["total_lines"] == 3


def test_ssid_profile_flattens_parameter_value_rows() -> None:
    raw = {
        "Profile Block": [
            {"Parameter": "ESSID", "Value": "lab-ssid"},
            {"Parameter": "Opmode", "Value": "wpa2-aes"},
        ]
    }
    out = normalize_payload("wlan_ssid_profile", raw)
    assert out["kind"] == "ssid_profile"
    assert out["parameters"]["ESSID"] == "lab-ssid"
    assert out["parameters"]["Opmode"] == "wpa2-aes"


def test_unknown_hint_falls_back_to_generic() -> None:
    out = normalize_payload("vlan", {"unrelated": "thing"})
    assert out == {"kind": "generic_json", "top_level_keys": ["unrelated"]}


def test_aaa_servers_normalizer_known_key() -> None:
    raw = {"Auth Servers": [{"Name": "rad1"}, {"Name": "rad2"}]}
    out = normalize_payload("aaa_servers", raw)
    assert out["kind"] == "servers"
    assert out["count"] == 2


def test_lc_cluster_normalizer_known_key() -> None:
    raw = {
        "Cluster Group-Membership Information": [
            {"Switch": "1.1.1.1", "State": "Active"},
            {"Switch": "1.1.1.2", "State": "Standby"},
        ]
    }
    out = normalize_payload("lc_cluster", raw)
    assert out["kind"] == "members"
    assert out["count"] == 2


@pytest.mark.parametrize(
    "non_dict",
    [None, "raw text only", 12345],
)
def test_table_normalizers_tolerate_non_dict_inputs(non_dict: object) -> None:
    assert normalize_payload("ap_database", non_dict) is None
