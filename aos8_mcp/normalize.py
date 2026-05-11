"""Optional normalization on top of raw showcommand payloads."""

from __future__ import annotations

from typing import Any

from aos8_mcp.show_registry import NormalizerHint


def normalize_payload(hint: NormalizerHint, raw: Any) -> dict[str, Any] | None:
    if hint == "generic":
        return _generic_json_shape(raw)
    if hint == "switches":
        return _list_named(raw, ("All Switches", "Switches"), "switches")
    if hint == "global_users":
        return _list_named(raw, ("Global Users",), "users")
    if hint == "ap_database":
        return _list_named(raw, ("AP Database",), "access_points")
    if hint == "log_text":
        return _log_shape(raw)
    if hint == "wlan_virtual_ap":
        return _list_named(raw, ("Virtual AP profile List",), "virtual_aps")
    if hint == "wlan_ssid_profile":
        return _ssid_profile(raw)
    return None


def _generic_json_shape(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        keys = [k for k in raw.keys() if not str(k).startswith("_")]
        return {"kind": "generic_json", "top_level_keys": keys[:50]}
    if isinstance(raw, list):
        return {"kind": "generic_json_array", "length": len(raw)}
    return None


def _list_named(raw: Any, candidate_keys: tuple[str, ...], out_key: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    for ck in candidate_keys:
        rows = raw.get(ck)
        if isinstance(rows, list):
            return {"kind": out_key, "count": len(rows), "items": rows}
    return _generic_json_shape(raw)


def _log_shape(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict) and raw.get("_format") == "log_xml_wrapper":
        lines = raw.get("lines") or []
        return {"kind": "log", "line_count": len(lines), "head": lines[:20], "tail": lines[-20:] if len(lines) > 40 else []}
    if isinstance(raw, dict) and raw.get("_format") == "text":
        t = str(raw.get("_raw_text", ""))
        lines = [ln for ln in t.splitlines() if ln.strip()]
        return {"kind": "log", "line_count": len(lines), "head": lines[:20], "tail": lines[-20:] if len(lines) > 40 else []}
    return None


def _ssid_profile(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    for key, val in raw.items():
        if str(key).startswith("_"):
            continue
        if isinstance(val, list) and val and isinstance(val[0], dict):
            if "Parameter" in val[0] and "Value" in val[0]:
                flat = {str(row.get("Parameter")): row.get("Value") for row in val if isinstance(row, dict)}
                return {"kind": "ssid_profile", "profile_block": key, "parameters": flat}
    return _generic_json_shape(raw)
