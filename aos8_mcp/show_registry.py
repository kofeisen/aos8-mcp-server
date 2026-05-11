"""Default show commands per domain — extend by adding entries here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


NormalizerHint = Literal[
    "switches",
    "global_users",
    "ap_database",
    "log_text",
    "wlan_virtual_ap",
    "wlan_ssid_profile",
    "generic",
]


@dataclass(frozen=True)
class DomainShowSpec:
    """Maps an MCP domain tool to its default CLI and optional normalizer hint."""

    domain: str
    default_command: str
    normalizer: NormalizerHint = "generic"
    description: str = ""


# Initial catalogue; add rows to expose new defaults without touching tool wiring.
DOMAIN_SPECS: dict[str, DomainShowSpec] = {
    "controllers": DomainShowSpec(
        domain="controllers",
        default_command="show switches",
        normalizer="switches",
        description="Mobility / switch hierarchy on MM",
    ),
    "clients": DomainShowSpec(
        domain="clients",
        default_command="show global-user-table list",
        normalizer="global_users",
        description="Global user (client) table",
    ),
    "aps": DomainShowSpec(
        domain="aps",
        default_command="show ap database",
        normalizer="ap_database",
        description="AP database (IP, group, flags, status)",
    ),
    "log": DomainShowSpec(
        domain="log",
        default_command="show log all",
        normalizer="log_text",
        description="Full local log buffer (use | include / exclude to narrow)",
    ),
    "wlan": DomainShowSpec(
        domain="wlan",
        default_command="show wlan virtual-ap",
        normalizer="wlan_virtual_ap",
        description="Virtual AP profiles; use wlan_mode=ssid_profile for SSID profile blocks",
    ),
}


def get_spec(domain: str) -> DomainShowSpec:
    if domain not in DOMAIN_SPECS:
        raise KeyError(f"Unknown domain {domain!r}; known: {sorted(DOMAIN_SPECS)}")
    return DOMAIN_SPECS[domain]


# --- show ap 变体（aos8_aps 的 variant 参数；键为 snake_case，连字符可写成下划线）---
# 值: (完整 CLI, normalizer)
AP_SHOW_VARIANTS: dict[str, tuple[str, NormalizerHint]] = {
    "active": ("show ap active", "generic"),
    "allowed_max_eirp": ("show ap allowed-max-EIRP", "generic"),
    "ap_group": ("show ap ap-group", "generic"),
    "ap_name": ("show ap ap-name", "generic"),
    "arm": ("show ap arm", "generic"),
    "assoc_throttle_counters": ("show ap assoc-throttle-counters", "generic"),
    "association": ("show ap association", "generic"),
    "authorization_profile": ("show ap authorization-profile", "generic"),
    "blacklist_clients": ("show ap blacklist-clients", "generic"),
    "denylist_clients": ("show ap denylist-clients", "generic"),
    "blacklist_protected": ("show ap blacklist-protected", "generic"),
    "denylist_protected": ("show ap denylist-protected", "generic"),
    "blacklist_time": ("show ap blacklist-time", "generic"),
    "denylist_time": ("show ap denylist-time", "generic"),
    "ble_database": ("show ap ble-database", "generic"),
    "ble_ibeacon_info": ("show ap ble-ibeacon-info", "generic"),
    "bss_table": ("show ap bss-table", "generic"),
    "bw_report": ("show ap bw-report", "generic"),
    "cellular": ("show ap cellular", "generic"),
    "client": ("show ap client", "generic"),
    "cluster_tech_support": ("show ap cluster-tech-support", "generic"),
    "config": ("show ap config", "generic"),
    "database": ("show ap database", "ap_database"),
    "database_summary": ("show ap database-summary", "generic"),
    "debug": ("show ap debug", "generic"),
    "deploy_profile": ("show ap deploy-profile", "generic"),
    "details": ("show ap details", "generic"),
    "dot1x": ("show ap dot1x", "generic"),
    "enet_link_profile": ("show ap enet-link-profile", "generic"),
    "essid": ("show ap essid", "generic"),
    "est_status": ("show ap est-status", "generic"),
    "general_profile": ("show ap general-profile", "generic"),
    "get_crash_dumps_status": ("show ap get-crash-dumps-status", "generic"),
    "ap_global": ("show ap global", "generic"),
    "greenap": ("show ap greenap", "generic"),
    "he_rates": ("show ap he-rates", "generic"),
    "ht_rates": ("show ap ht-rates", "generic"),
    "image": ("show ap image", "generic"),
    "image_preload": ("show ap image-preload", "generic"),
    "ip": ("show ap ip", "generic"),
    "radio-database": ("Shows radio information for APs that are visible to the controller.", "generic"),
    "radio-table": ("show ap radio-table", "generic"),
    "radio-table-summary": ("show ap radio-table-summary", "generic"),
    "radio-table-summary-detailed": ("show ap radio-table-summary-detailed", "generic"),
    "radio-table-summary-detailed-detailed": ("show ap radio-table-summary-detailed-detailed", "generic"),
    "radio-table-summary-detailed-detailed-detailed": ("show ap radio-table-summary-detailed-detailed-detailed", "generic"),
    "radio-table-summary-detailed-detailed-detailed-detailed": ("show ap radio-table-summary-detailed-detailed-detailed-detailed", "generic"),
    "radio-table-summary-detailed-detailed-detailed-detailed-detailed": ("show ap radio-table-summary-detailed-detailed-detailed-detailed-detailed", "generic"),
}


def normalize_ap_variant_key(variant: str) -> str:
    return variant.strip().lower().replace("-", "_")


def resolve_ap_variant(variant: str) -> tuple[str, NormalizerHint]:
    """解析 aos8_aps 的 variant，返回 (show 命令, normalizer)。"""
    key = normalize_ap_variant_key(variant)
    if key == "global":
        key = "ap_global"
    if key not in AP_SHOW_VARIANTS:
        choices = ", ".join(sorted(AP_SHOW_VARIANTS))
        raise ValueError(f"未知的 ap variant {variant!r}。可选键: {choices}")
    return AP_SHOW_VARIANTS[key]


def ap_variant_catalog() -> dict[str, str]:
    """variant -> CLI，供列表工具与文档生成。"""
    return {k: v[0] for k, v in sorted(AP_SHOW_VARIANTS.items())}
