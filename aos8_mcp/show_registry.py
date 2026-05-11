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
        description="show ap 子命令由 variant 选择；见 AP_SHOW_VARIANTS 与 aos8_ap_show_variants",
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
        description="show wlan 子命令见 WLAN_SHOW_VARIANTS（与 AP 相同的三元组）；aos8_wlan_show_variants",
    ),
}


def get_spec(domain: str) -> DomainShowSpec:
    if domain not in DOMAIN_SPECS:
        raise KeyError(f"Unknown domain {domain!r}; known: {sorted(DOMAIN_SPECS)}")
    return DOMAIN_SPECS[domain]


# --- show ap 变体（aos8_aps 的 variant；键仅用 snake_case，连字符在入参里会规范为下划线）---
# 值: (完整 CLI, normalizer, 英文简述 — 与 AOS8 CLI Bank 一致，便于模型选型)
AP_SHOW_VARIANTS: dict[str, tuple[str, NormalizerHint, str]] = {
    "active": (
        "show ap active",
        "generic",
        "APs currently registered or having clients terminating (in cluster) on this switch.",
    ),
    "allowed_max_eirp": (
        "show ap allowed-max-EIRP",
        "generic",
        "Max EIRP setting per country per AP type.",
    ),
    "ap_group": (
        "show ap ap-group",
        "generic",
        "Contents of AP's group.",
    ),
    "ap_lacp_striping_ip": (
        "show ap ap-lacp-striping-ip",
        "generic",
        "Profile to enable/disable AP LACP and GRE striping IP to LMS IP mapping.",
    ),
    "ap_name": (
        "show ap ap-name",
        "generic",
        "List of AP names.",
    ),
    "arm": ("show ap arm", "generic", "ARM information."),
    "assoc_throttle_counters": (
        "show ap assoc-throttle-counters",
        "generic",
        "Counters related to association request throttling.",
    ),
    "association": (
        "show ap association",
        "generic",
        "Association table for an AP.",
    ),
    "authorization_profile": (
        "show ap authorization-profile",
        "generic",
        "An AP Authorization profile.",
    ),
    "blacklist_clients": (
        "show ap blacklist-clients",
        "generic",
        "Clients denied access (legacy blacklist naming).",
    ),
    "denylist_clients": (
        "show ap denylist-clients",
        "generic",
        "Clients denied access (denylist naming).",
    ),
    "blacklist_protected": (
        "show ap blacklist-protected",
        "generic",
        "Clients protected against further traffic steering for a period (blacklist naming).",
    ),
    "denylist_protected": (
        "show ap denylist-protected",
        "generic",
        "Clients protected against further traffic steering (denylist naming).",
    ),
    "blacklist_time": (
        "show ap blacklist-time",
        "generic",
        "Blacklist time between disconnection and user-timeout (blacklist naming).",
    ),
    "denylist_time": (
        "show ap denylist-time",
        "generic",
        "Denylist time between disconnection and user-timeout (denylist naming).",
    ),
    "ble_database": (
        "show ap ble-database",
        "generic",
        "BLE APB information collected by BLE relay.",
    ),
    "ble_ibeacon_info": (
        "show ap ble-ibeacon-info",
        "generic",
        "AP BLE radio iBeacon parameters.",
    ),
    "bss_table": (
        "show ap bss-table",
        "generic",
        "BSSIDs of all APs registered on this switch.",
    ),
    "bw_report": (
        "show ap bw-report",
        "generic",
        "Bandwidth allocation report for an AP.",
    ),
    "cellular": (
        "show ap cellular",
        "generic",
        "Cellular information for an AP.",
    ),
    "client": (
        "show ap client",
        "generic",
        "Wireless client-specific information.",
    ),
    "cluster_tech_support": (
        "show ap cluster-tech-support",
        "generic",
        "Cluster information for an AP.",
    ),
    "config": (
        "show ap config",
        "generic",
        "AP configuration parameters.",
    ),
    "consolidated_provision": (
        "show ap consolidated-provision",
        "generic",
        "Consolidated provision details of an AP.",
    ),
    "convert_download_log": (
        "show ap convert-download-log",
        "generic",
        "Conversion image downloading logs.",
    ),
    "convert_image_list": (
        "show ap convert-image-list",
        "generic",
        "All available images for conversion.",
    ),
    "convert_setup_image_log": (
        "show ap convert-setup-image-log",
        "generic",
        "Conversion setup image logs.",
    ),
    "convert_status": (
        "show ap convert-status",
        "generic",
        "Status of AP image conversion operation.",
    ),
    "convert_status_list": (
        "show ap convert-status-list",
        "generic",
        "List of APs and their conversion statuses only.",
    ),
    "convert_status_summary": (
        "show ap convert-status-summary",
        "generic",
        "Status summary of conversion operation.",
    ),
    "crash_transfer": (
        "show ap crash-transfer",
        "generic",
        "AP crash transfer feature (coredump to controller flash when no dumpserver).",
    ),
    "database": (
        "show ap database",
        "ap_database",
        "List of access points in the database.",
    ),
    "database_summary": (
        "show ap database-summary",
        "generic",
        "General summary of AP information for the controller.",
    ),
    "debug": ("show ap debug", "generic", "Debugging information of an AP."),
    "deploy_profile": (
        "show ap deploy-profile",
        "generic",
        "The AP deploy-profile.",
    ),
    "details": ("show ap details", "generic", "Details about an AP."),
    "dot1x": ("show ap dot1x", "generic", "Details about an 802.1X AP."),
    "enet_link_profile": (
        "show ap enet-link-profile",
        "generic",
        "An AP Ethernet Link profile.",
    ),
    "essid": ("show ap essid", "generic", "ESSID information."),
    "est_status": (
        "show ap est-status",
        "generic",
        "Contents of /tmp/est_status for an AP.",
    ),
    "general_profile": (
        "show ap general-profile",
        "generic",
        "The AP general-profile.",
    ),
    "get_crash_dumps_status": (
        "show ap get-crash-dumps-status",
        "generic",
        "Get crash dumps status.",
    ),
    "ap_global": (
        "show ap global",
        "generic",
        "AP central database.",
    ),
    "greenap": (
        "show ap greenap",
        "generic",
        "AP supporting green mode.",
    ),
    "he_rates": (
        "show ap he-rates",
        "generic",
        "High-efficiency rate information for a BSS.",
    ),
    "ht_rates": (
        "show ap ht-rates",
        "generic",
        "High-throughput rate information for a BSS.",
    ),
    "image": ("show ap image", "generic", "AP image version."),
    "image_preload": (
        "show ap image-preload",
        "generic",
        "Status of AP image preload operation.",
    ),
    "ip": (
        "show ap ip",
        "generic",
        "Health check IP probe mode.",
    ),
    "radio_database": (
        "show ap radio-database",
        "generic",
        "AP radio database.",
    ),
    "radio_table": (
        "show ap radio-table",
        "generic",
        "AP radio table.",
    ),
    "radio_summary": (
        "show ap radio-summary",
        "generic",
        "AP radio summary.",
    ),
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
    cmd, hint, _desc = AP_SHOW_VARIANTS[key]
    return cmd, hint


def ap_variant_catalog() -> dict[str, dict[str, str]]:
    """variant -> { command, description }，供 aos8_ap_show_variants 与文档。"""
    return {
        k: {"command": v[0], "description": v[2]}
        for k, v in sorted(AP_SHOW_VARIANTS.items())
    }


# --- show wlan 变体（与 AP 相同：命令 + normalizer + 英文描述；profile_name 由 server 追加）---
WLAN_SHOW_VARIANTS: dict[str, tuple[str, NormalizerHint, str]] = {
    "virtual_ap": (
        "show wlan virtual-ap",
        "wlan_virtual_ap",
        "Virtual AP profile settings.",
    ),
    "six_ghz_rrm_ie_profile": (
        "show wlan 6ghz-rrm-ie-profile",
        "generic",
        "RRM IE profile for 6 GHz.",
    ),
    "anyspot_profile": (
        "show wlan anyspot-profile",
        "generic",
        "Anyspot profile.",
    ),
    "bcn_rpt_req_profile": (
        "show wlan bcn-rpt-req-profile",
        "generic",
        "Beacon Report Request frames profile.",
    ),
    "client_wlan_profile": (
        "show wlan client-wlan-profile",
        "generic",
        "WLAN profile configuration for a VIA client.",
    ),
    "dot11k_profile": (
        "show wlan dot11k-profile",
        "generic",
        "802.11k profiles (list or detail).",
    ),
    "dot11r_profile": (
        "show wlan dot11r-profile",
        "generic",
        "802.11r profiles (list or detail).",
    ),
    "edca_parameters_profile": (
        "show wlan edca-parameters-profile",
        "generic",
        "EDCA profile for APs or stations.",
    ),
    "he_ssid_profile": (
        "show wlan he-ssid-profile",
        "wlan_ssid_profile",
        "High-efficiency (802.11ax) SSID profile configuration.",
    ),
    "hotspot": (
        "show wlan hotspot",
        "generic",
        "Hotspot 2.0 profile settings.",
    ),
    "ht_ssid_profile": (
        "show wlan ht-ssid-profile",
        "wlan_ssid_profile",
        "High-throughput SSID profile settings.",
    ),
    "mu_edca_parameters_profile": (
        "show wlan mu-edca-parameters-profile",
        "generic",
        "MU EDCA parameters profile settings.",
    ),
    "rrm_ie_profile": (
        "show wlan rrm-ie-profile",
        "generic",
        "RRM IE profile settings.",
    ),
    "sae_profile": (
        "show wlan sae-profile",
        "generic",
        "WPA3 SAE configuration profile settings.",
    ),
    "ssid_profile": (
        "show wlan ssid-profile",
        "wlan_ssid_profile",
        "SSID profile settings.",
    ),
    "traffic_management_profile": (
        "show wlan traffic-management-profile",
        "generic",
        "Traffic management profile settings.",
    ),
    "tsm_req_profile": (
        "show wlan tsm-req-profile",
        "generic",
        "TSM Report Request profile settings.",
    ),
    "wmm_traffic_management_profile": (
        "show wlan wmm-traffic-management-profile",
        "generic",
        "WMM traffic management profile settings.",
    ),
}


def normalize_wlan_variant_key(variant: str) -> str:
    return variant.strip().lower().replace("-", "_")


def resolve_wlan_variant(variant: str) -> tuple[str, NormalizerHint]:
    key = normalize_wlan_variant_key(variant)
    if key not in WLAN_SHOW_VARIANTS:
        choices = ", ".join(sorted(WLAN_SHOW_VARIANTS))
        raise ValueError(f"未知的 wlan variant {variant!r}。可选键: {choices}")
    cmd, hint, _desc = WLAN_SHOW_VARIANTS[key]
    return cmd, hint


def wlan_variant_catalog() -> dict[str, dict[str, str]]:
    """与 ap_variant_catalog 相同：variant -> { command, description }。"""
    return {
        k: {"command": v[0], "description": v[2]}
        for k, v in sorted(WLAN_SHOW_VARIANTS.items())
    }
