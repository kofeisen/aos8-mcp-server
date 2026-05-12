"""Heuristic normalization on top of raw ``showcommand`` payloads.

The Aruba ``showcommand`` JSON shape varies wildly by CLI. To make it easier
for the LLM to answer simple aggregate questions ("how many APs are up?",
"how many users are online?"), we recognise a handful of common shapes and
return ``{kind, count, items}``-style summaries. The original payload is
always preserved under ``raw`` by the caller.
"""

from __future__ import annotations

from typing import Any

from aos8_mcp.show_registry import NormalizerHint


# Keys that, when present, contain the "main" tabular content of a payload.
_TABLE_CANDIDATE_KEYS: dict[NormalizerHint, tuple[str, ...]] = {
    "switches": ("All Switches", "Switches"),
    "global_users": ("Global Users",),
    "ap_database": ("AP Database",),
    "ap_active": ("Active AP Table", "Active APs"),
    "ap_radio_summary": ("AP Radio Summary", "Radio Summary"),
    "ap_bss_table": ("Aruba AP BSS Table", "AP BSS Table"),
    "ap_monitor": ("Monitored APs", "AP Monitor Stats"),
    "wlan_virtual_ap": ("Virtual AP profile List",),
    "user_table": ("Users",),
    "user_role": ("Role List", "Roles"),
    "vlan": ("VLAN", "VLANs"),
    "port_status": ("Port Status", "Ports"),
    "ip_interface_brief": ("Interface Table", "IP Interface List"),
    "ip_route": ("IP Route Table", "Routes"),
    "ip_ospf_neighbor": ("OSPF Neighbor List", "Neighbors"),
    "arp_table": ("ARP Table", "ARP Entries"),
    "license_summary": ("License Table", "Licenses"),
    "lc_cluster": (
        "Cluster Group-Membership Information",
        "Group Membership Information",
        "Cluster Members",
    ),
    "aaa_servers": ("Auth Servers", "Auth Server Table"),
}


def normalize_payload(hint: NormalizerHint, raw: Any) -> dict[str, Any] | None:
    """Dispatch to a normalizer based on the registry hint."""
    if hint == "generic":
        return _generic_json_shape(raw)
    if hint == "log_text":
        return _log_shape(raw)
    if hint == "wlan_ssid_profile":
        return _ssid_profile(raw)
    if hint in _TABLE_CANDIDATE_KEYS:
        return _table_shape(raw, _TABLE_CANDIDATE_KEYS[hint], _out_key(hint))
    return _generic_json_shape(raw)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_OUT_KEY: dict[NormalizerHint, str] = {
    "switches": "switches",
    "global_users": "users",
    "ap_database": "access_points",
    "ap_active": "active_aps",
    "ap_radio_summary": "radios",
    "ap_bss_table": "bssids",
    "ap_monitor": "monitor_entries",
    "wlan_virtual_ap": "virtual_aps",
    "user_table": "users",
    "user_role": "roles",
    "vlan": "vlans",
    "port_status": "ports",
    "ip_interface_brief": "interfaces",
    "ip_route": "routes",
    "ip_ospf_neighbor": "neighbors",
    "arp_table": "entries",
    "license_summary": "licenses",
    "lc_cluster": "members",
    "aaa_servers": "servers",
}


def _out_key(hint: NormalizerHint) -> str:
    return _OUT_KEY.get(hint, "items")


def _generic_json_shape(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        keys = [k for k in raw.keys() if not str(k).startswith("_")]
        return {"kind": "generic_json", "top_level_keys": keys[:50]}
    if isinstance(raw, list):
        return {"kind": "generic_json_array", "length": len(raw)}
    return None


def _table_shape(
    raw: Any, candidate_keys: tuple[str, ...], out_key: str
) -> dict[str, Any] | None:
    """Pull a list of row-dicts out of one of the candidate top-level keys.

    Falls back to scanning all top-level lists if none of the well-known keys
    are present — keeps things resilient when the controller renames a header.
    """
    if not isinstance(raw, dict):
        return None
    for ck in candidate_keys:
        rows = raw.get(ck)
        if isinstance(rows, list):
            return {"kind": out_key, "count": len(rows), "items": rows}
    # 兜底：找一个最大的 list-of-dict
    fallback: list[Any] | None = None
    fallback_src: str | None = None
    for k, v in raw.items():
        if str(k).startswith("_"):
            continue
        if isinstance(v, list) and v and isinstance(v[0], dict):
            if fallback is None or len(v) > len(fallback):
                fallback = v
                fallback_src = k
    if fallback is not None:
        return {
            "kind": out_key,
            "count": len(fallback),
            "items": fallback,
            "source_key": fallback_src,
        }
    return _generic_json_shape(raw)


def _log_shape(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict) and raw.get("_format") == "log_xml_wrapper":
        lines = raw.get("lines") or []
        return _log_summary(lines)
    if isinstance(raw, dict) and raw.get("_format") == "text":
        t = str(raw.get("_raw_text", ""))
        lines = [ln for ln in t.splitlines() if ln.strip()]
        return _log_summary(lines)
    # show log all may also come back as plain JSON dict with a "log" key in
    # some AOS variants; try to be lenient.
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list) and v and isinstance(v[0], str):
                return _log_summary(list(v))
    return None


def _log_summary(lines: list[str]) -> dict[str, Any]:
    n = len(lines)
    head = lines[:20]
    tail = lines[-20:] if n > 40 else []
    return {"kind": "log", "line_count": n, "head": head, "tail": tail}


def _ssid_profile(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    for key, val in raw.items():
        if str(key).startswith("_"):
            continue
        if isinstance(val, list) and val and isinstance(val[0], dict):
            if "Parameter" in val[0] and "Value" in val[0]:
                flat = {
                    str(row.get("Parameter")): row.get("Value")
                    for row in val
                    if isinstance(row, dict)
                }
                return {
                    "kind": "ssid_profile",
                    "profile_block": key,
                    "parameters": flat,
                }
    return _generic_json_shape(raw)
