"""Catalogue of read-only ``show`` presets exposed to the MCP tools.

Each preset carries enough metadata for the tool layer to:
  * pick the right CLI command,
  * choose a structured normalizer for the response,
  * decide an appropriate cache lifetime, and
  * surface a human-readable description to the LLM.

To register a new ``show`` command, add a row to the relevant ``*_PRESETS``
dictionary (or create a new domain with ``register_domain``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


NormalizerHint = Literal[
    "switches",
    "global_users",
    "ap_database",
    "ap_active",
    "ap_radio_summary",
    "ap_bss_table",
    "ap_monitor",
    "log_text",
    "wlan_virtual_ap",
    "wlan_ssid_profile",
    "user_table",
    "user_role",
    "vlan",
    "port_status",
    "ip_interface_brief",
    "ip_route",
    "ip_ospf_neighbor",
    "arp_table",
    "license_summary",
    "lc_cluster",
    "aaa_servers",
    "generic",
]

CacheTier = Literal["static", "near_realtime", "realtime"]


@dataclass(frozen=True)
class ShowPreset:
    """A registered ``show`` command exposed via an MCP domain tool."""

    key: str
    command: str
    description: str
    normalizer: NormalizerHint = "generic"
    cache_tier: CacheTier = "near_realtime"
    # When True, the caller is expected to pass ``profile_name`` so the final
    # CLI becomes ``<command> <profile_name>`` (used by ``show wlan
    # *-ssid-profile`` family). ``profile_name_default`` is appended when the
    # caller omits a name.
    needs_profile_name: bool = False
    profile_name_default: str | None = None


def normalize_key(key: str) -> str:
    """Map ``my-variant`` / ``MyVariant`` to ``my_variant`` for lookups."""
    return key.strip().lower().replace("-", "_")


# ---------------------------------------------------------------------------
# Domain: controllers (mobility hierarchy on MM)
# ---------------------------------------------------------------------------
CONTROLLERS_PRESETS: dict[str, ShowPreset] = {
    "switches": ShowPreset(
        key="switches",
        command="show switches",
        description="All controllers (MM/MD) registered in the hierarchy.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switches_state_down": ShowPreset(
        key="switches_state_down",
        command="show switches state down",
        description="Controllers currently in DOWN state.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switch_software": ShowPreset(
        key="switch_software",
        command="show switch software",
        description="Software version installed on the local controller.",
        normalizer="generic",
        cache_tier="static",
    ),
    "switch_ip": ShowPreset(
        key="switch_ip",
        command="show switch ip",
        description="Controller management IP and related parameters.",
        normalizer="generic",
        cache_tier="static",
    ),
}

# ---------------------------------------------------------------------------
# Domain: clients (associated wireless users)
# ---------------------------------------------------------------------------
CLIENTS_PRESETS: dict[str, ShowPreset] = {
    "global_user_table_list": ShowPreset(
        key="global_user_table_list",
        command="show global-user-table list",
        description="Hierarchy-wide list of associated wireless users (one row per user).",
        normalizer="global_users",
        cache_tier="near_realtime",
    ),
    "global_user_table_count": ShowPreset(
        key="global_user_table_count",
        command="show global-user-table count",
        description="Aggregate counters across the user table.",
        normalizer="generic",
        cache_tier="near_realtime",
    ),
    "user_table": ShowPreset(
        key="user_table",
        command="show user-table",
        description="Local user table on the controller (verbose).",
        normalizer="user_table",
        cache_tier="near_realtime",
    ),
    "user_summary": ShowPreset(
        key="user_summary",
        command="show user-summary",
        description="High-level summary of users by role / radio.",
        normalizer="generic",
        cache_tier="near_realtime",
    ),
    "user_role": ShowPreset(
        key="user_role",
        command="show rights",
        description="All user roles defined on the device.",
        normalizer="user_role",
        cache_tier="static",
    ),
    "datapath_user_table": ShowPreset(
        key="datapath_user_table",
        command="show datapath user table",
        description="Datapath view of users (for hands-on debugging).",
        normalizer="generic",
        cache_tier="realtime",
    ),
}

# ---------------------------------------------------------------------------
# Domain: log
# ---------------------------------------------------------------------------
LOG_PRESETS: dict[str, ShowPreset] = {
    "all": ShowPreset(
        key="all",
        command="show log all",
        description="Full controller log buffer (large; prefer cli_suffix or tail_lines).",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "errorlog": ShowPreset(
        key="errorlog",
        command="show log errorlog all",
        description="Errors recorded in the controller log.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "security": ShowPreset(
        key="security",
        command="show log security all",
        description="Security-related log entries.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "system": ShowPreset(
        key="system",
        command="show log system all",
        description="System log subset.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "user": ShowPreset(
        key="user",
        command="show log user all",
        description="User-facing log entries (auth, association).",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "wireless": ShowPreset(
        key="wireless",
        command="show log wireless all",
        description="Wireless subsystem log entries.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
}

# ---------------------------------------------------------------------------
# Domain: aps  (extensive ``show ap *`` set, denylist naming only)
# ---------------------------------------------------------------------------
AP_PRESETS: dict[str, ShowPreset] = {
    "active": ShowPreset(
        key="active",
        command="show ap active",
        description="APs currently registered or with clients terminating on this controller.",
        normalizer="ap_active",
        cache_tier="near_realtime",
    ),
    "allowed_max_eirp": ShowPreset(
        key="allowed_max_eirp",
        command="show ap allowed-max-EIRP",
        description="Maximum EIRP setting per country per AP type.",
        cache_tier="static",
    ),
    "ap_group": ShowPreset(
        key="ap_group",
        command="show ap ap-group",
        description="Members and configuration of AP groups.",
        cache_tier="static",
    ),
    "ap_lacp_striping_ip": ShowPreset(
        key="ap_lacp_striping_ip",
        command="show ap ap-lacp-striping-ip",
        description="AP LACP and GRE striping IP / LMS IP mapping profile.",
        cache_tier="static",
    ),
    "ap_name": ShowPreset(
        key="ap_name",
        command="show ap ap-name",
        description="List of AP names known on the controller.",
        cache_tier="near_realtime",
    ),
    "arm": ShowPreset(
        key="arm",
        command="show ap arm",
        description="Adaptive Radio Management top-level info.",
    ),
    "arm_rf_summary": ShowPreset(
        key="arm_rf_summary",
        command="show ap arm rf-summary",
        description="Per-radio ARM RF summary (channel, power, noise).",
        cache_tier="near_realtime",
    ),
    "assoc_throttle_counters": ShowPreset(
        key="assoc_throttle_counters",
        command="show ap assoc-throttle-counters",
        description="Association request throttling counters.",
    ),
    "association": ShowPreset(
        key="association",
        command="show ap association",
        description="Association table for an AP.",
        cache_tier="near_realtime",
    ),
    "authorization_profile": ShowPreset(
        key="authorization_profile",
        command="show ap authorization-profile",
        description="AP authorization profile.",
        cache_tier="static",
    ),
    "ble_database": ShowPreset(
        key="ble_database",
        command="show ap ble-database",
        description="BLE APB information collected by the BLE relay.",
    ),
    "ble_ibeacon_info": ShowPreset(
        key="ble_ibeacon_info",
        command="show ap ble-ibeacon-info",
        description="BLE radio iBeacon parameters.",
    ),
    "bss_table": ShowPreset(
        key="bss_table",
        command="show ap bss-table",
        description="BSSIDs of all APs registered on this controller.",
        normalizer="ap_bss_table",
        cache_tier="near_realtime",
    ),
    "bw_report": ShowPreset(
        key="bw_report",
        command="show ap bw-report",
        description="Bandwidth allocation report for an AP.",
    ),
    "cellular": ShowPreset(
        key="cellular",
        command="show ap cellular",
        description="Cellular information for an AP.",
    ),
    "client": ShowPreset(
        key="client",
        command="show ap client",
        description="Wireless client-specific information from the AP view.",
    ),
    "cluster_tech_support": ShowPreset(
        key="cluster_tech_support",
        command="show ap cluster-tech-support",
        description="Cluster diagnostic snapshot for an AP.",
    ),
    "config": ShowPreset(
        key="config",
        command="show ap config",
        description="AP configuration parameters.",
        cache_tier="static",
    ),
    "consolidated_provision": ShowPreset(
        key="consolidated_provision",
        command="show ap consolidated-provision",
        description="Consolidated provisioning details of an AP.",
    ),
    "convert_download_log": ShowPreset(
        key="convert_download_log",
        command="show ap convert-download-log",
        description="Conversion image download logs.",
    ),
    "convert_image_list": ShowPreset(
        key="convert_image_list",
        command="show ap convert-image-list",
        description="Available conversion images.",
    ),
    "convert_setup_image_log": ShowPreset(
        key="convert_setup_image_log",
        command="show ap convert-setup-image-log",
        description="Conversion setup image logs.",
    ),
    "convert_status": ShowPreset(
        key="convert_status",
        command="show ap convert-status",
        description="Image conversion status for an AP.",
    ),
    "convert_status_list": ShowPreset(
        key="convert_status_list",
        command="show ap convert-status-list",
        description="List of APs and their conversion statuses.",
    ),
    "convert_status_summary": ShowPreset(
        key="convert_status_summary",
        command="show ap convert-status-summary",
        description="Status summary of the conversion operation.",
    ),
    "crash_transfer": ShowPreset(
        key="crash_transfer",
        command="show ap crash-transfer",
        description="AP crash transfer feature (coredump to controller flash).",
    ),
    "database": ShowPreset(
        key="database",
        command="show ap database",
        description="List of access points in the database (up/down/flags).",
        normalizer="ap_database",
        cache_tier="near_realtime",
    ),
    "database_summary": ShowPreset(
        key="database_summary",
        command="show ap database-summary",
        description="Aggregate summary of AP database (counts by status).",
        cache_tier="near_realtime",
    ),
    "debug": ShowPreset(
        key="debug",
        command="show ap debug",
        description="Top-level debug index for an AP.",
        cache_tier="realtime",
    ),
    "debug_system_status": ShowPreset(
        key="debug_system_status",
        command="show ap debug system-status",
        description="Detailed AP system status (CPU, memory, uptime).",
        cache_tier="realtime",
    ),
    "denylist_clients": ShowPreset(
        key="denylist_clients",
        command="show ap denylist-clients",
        description="Clients currently denied access.",
        cache_tier="near_realtime",
    ),
    "denylist_protected": ShowPreset(
        key="denylist_protected",
        command="show ap denylist-protected",
        description="Clients protected against further traffic steering.",
    ),
    "denylist_time": ShowPreset(
        key="denylist_time",
        command="show ap denylist-time",
        description="Denylist time between disconnection and user-timeout.",
        cache_tier="static",
    ),
    "deploy_profile": ShowPreset(
        key="deploy_profile",
        command="show ap deploy-profile",
        description="AP deploy-profile.",
        cache_tier="static",
    ),
    "details": ShowPreset(
        key="details",
        command="show ap details",
        description="Details about a specific AP (commonly with ``ap-name <name>`` suffix).",
    ),
    "dot1x": ShowPreset(
        key="dot1x",
        command="show ap dot1x",
        description="Details about an 802.1X AP.",
    ),
    "enet_link_profile": ShowPreset(
        key="enet_link_profile",
        command="show ap enet-link-profile",
        description="AP Ethernet link profile.",
        cache_tier="static",
    ),
    "essid": ShowPreset(
        key="essid",
        command="show ap essid",
        description="ESSID information visible from the controller.",
        cache_tier="near_realtime",
    ),
    "est_status": ShowPreset(
        key="est_status",
        command="show ap est-status",
        description="Contents of /tmp/est_status for an AP.",
    ),
    "general_profile": ShowPreset(
        key="general_profile",
        command="show ap general-profile",
        description="AP general-profile.",
        cache_tier="static",
    ),
    "get_crash_dumps_status": ShowPreset(
        key="get_crash_dumps_status",
        command="show ap get-crash-dumps-status",
        description="AP crash dumps status.",
    ),
    "ap_global": ShowPreset(
        key="ap_global",
        command="show ap global",
        description="Central AP database (synonym for the legacy ``show ap global`` view).",
    ),
    "greenap": ShowPreset(
        key="greenap",
        command="show ap greenap",
        description="APs supporting green-mode power saving.",
    ),
    "he_rates": ShowPreset(
        key="he_rates",
        command="show ap he-rates",
        description="High-efficiency (802.11ax) rate information for a BSS.",
    ),
    "ht_rates": ShowPreset(
        key="ht_rates",
        command="show ap ht-rates",
        description="High-throughput (802.11n) rate information for a BSS.",
    ),
    "image": ShowPreset(
        key="image",
        command="show ap image",
        description="AP image version.",
        cache_tier="static",
    ),
    "image_preload": ShowPreset(
        key="image_preload",
        command="show ap image-preload",
        description="Status of AP image preload operation.",
    ),
    "ip": ShowPreset(
        key="ip",
        command="show ap ip",
        description="Health check IP probe mode.",
    ),
    "monitor_stats": ShowPreset(
        key="monitor_stats",
        command="show ap monitor stats",
        description="Air monitor statistics (interference / scan).",
        normalizer="ap_monitor",
        cache_tier="near_realtime",
    ),
    "radio_database": ShowPreset(
        key="radio_database",
        command="show ap radio-database",
        description="AP radio database.",
        cache_tier="near_realtime",
    ),
    "radio_table": ShowPreset(
        key="radio_table",
        command="show ap radio-table",
        description="AP radio table.",
        cache_tier="near_realtime",
    ),
    "radio_summary": ShowPreset(
        key="radio_summary",
        command="show ap radio-summary",
        description="AP radio summary across the hierarchy.",
        normalizer="ap_radio_summary",
        cache_tier="near_realtime",
    ),
}

# Convenience aliases (legacy / common typos).
_AP_ALIASES = {
    "global": "ap_global",
    "rf_summary": "arm_rf_summary",
}

# ---------------------------------------------------------------------------
# Domain: wlan (``show wlan *``)
# ---------------------------------------------------------------------------
WLAN_PRESETS: dict[str, ShowPreset] = {
    "virtual_ap": ShowPreset(
        key="virtual_ap",
        command="show wlan virtual-ap",
        description="Virtual AP profile settings.",
        normalizer="wlan_virtual_ap",
        cache_tier="static",
    ),
    "six_ghz_rrm_ie_profile": ShowPreset(
        key="six_ghz_rrm_ie_profile",
        command="show wlan 6ghz-rrm-ie-profile",
        description="RRM IE profile for 6 GHz.",
        cache_tier="static",
    ),
    "anyspot_profile": ShowPreset(
        key="anyspot_profile",
        command="show wlan anyspot-profile",
        description="Anyspot profile.",
        cache_tier="static",
    ),
    "bcn_rpt_req_profile": ShowPreset(
        key="bcn_rpt_req_profile",
        command="show wlan bcn-rpt-req-profile",
        description="Beacon Report Request frames profile.",
        cache_tier="static",
    ),
    "client_wlan_profile": ShowPreset(
        key="client_wlan_profile",
        command="show wlan client-wlan-profile",
        description="WLAN profile configuration for a VIA client.",
        cache_tier="static",
    ),
    "dot11k_profile": ShowPreset(
        key="dot11k_profile",
        command="show wlan dot11k-profile",
        description="802.11k profiles (list or detail).",
        cache_tier="static",
    ),
    "dot11r_profile": ShowPreset(
        key="dot11r_profile",
        command="show wlan dot11r-profile",
        description="802.11r profiles (list or detail).",
        cache_tier="static",
    ),
    "edca_parameters_profile": ShowPreset(
        key="edca_parameters_profile",
        command="show wlan edca-parameters-profile",
        description="EDCA profile for APs or stations.",
        cache_tier="static",
    ),
    "he_ssid_profile": ShowPreset(
        key="he_ssid_profile",
        command="show wlan he-ssid-profile",
        description="High-efficiency (802.11ax) SSID profile configuration.",
        normalizer="wlan_ssid_profile",
        cache_tier="static",
        needs_profile_name=True,
        profile_name_default="default",
    ),
    "hotspot": ShowPreset(
        key="hotspot",
        command="show wlan hotspot",
        description="Hotspot 2.0 profile settings.",
        cache_tier="static",
    ),
    "ht_ssid_profile": ShowPreset(
        key="ht_ssid_profile",
        command="show wlan ht-ssid-profile",
        description="High-throughput SSID profile settings.",
        normalizer="wlan_ssid_profile",
        cache_tier="static",
        needs_profile_name=True,
        profile_name_default="default",
    ),
    "mu_edca_parameters_profile": ShowPreset(
        key="mu_edca_parameters_profile",
        command="show wlan mu-edca-parameters-profile",
        description="MU EDCA parameters profile settings.",
        cache_tier="static",
    ),
    "rrm_ie_profile": ShowPreset(
        key="rrm_ie_profile",
        command="show wlan rrm-ie-profile",
        description="RRM IE profile settings.",
        cache_tier="static",
    ),
    "sae_profile": ShowPreset(
        key="sae_profile",
        command="show wlan sae-profile",
        description="WPA3 SAE configuration profile settings.",
        cache_tier="static",
    ),
    "ssid_profile": ShowPreset(
        key="ssid_profile",
        command="show wlan ssid-profile",
        description="SSID profile settings.",
        normalizer="wlan_ssid_profile",
        cache_tier="static",
        needs_profile_name=True,
        profile_name_default="default",
    ),
    "traffic_management_profile": ShowPreset(
        key="traffic_management_profile",
        command="show wlan traffic-management-profile",
        description="Traffic management profile settings.",
        cache_tier="static",
    ),
    "tsm_req_profile": ShowPreset(
        key="tsm_req_profile",
        command="show wlan tsm-req-profile",
        description="TSM Report Request profile settings.",
        cache_tier="static",
    ),
    "wmm_traffic_management_profile": ShowPreset(
        key="wmm_traffic_management_profile",
        command="show wlan wmm-traffic-management-profile",
        description="WMM traffic management profile settings.",
        cache_tier="static",
    ),
}

# ---------------------------------------------------------------------------
# Domain: system  (platform health and identification)
# ---------------------------------------------------------------------------
SYSTEM_PRESETS: dict[str, ShowPreset] = {
    "version": ShowPreset(
        key="version",
        command="show version",
        description="Controller software/hardware version.",
        cache_tier="static",
    ),
    "inventory": ShowPreset(
        key="inventory",
        command="show inventory",
        description="Hardware inventory of the controller.",
        cache_tier="static",
    ),
    "license": ShowPreset(
        key="license",
        command="show license",
        description="Installed licenses on the controller.",
        normalizer="license_summary",
        cache_tier="static",
    ),
    "license_summary": ShowPreset(
        key="license_summary",
        command="show license summary",
        description="Aggregated license usage summary.",
        normalizer="license_summary",
        cache_tier="static",
    ),
    "cpuload": ShowPreset(
        key="cpuload",
        command="show cpuload",
        description="Current CPU load.",
        cache_tier="realtime",
    ),
    "memory": ShowPreset(
        key="memory",
        command="show memory",
        description="Memory utilization.",
        cache_tier="realtime",
    ),
    "storage": ShowPreset(
        key="storage",
        command="show storage",
        description="Flash storage usage.",
        cache_tier="near_realtime",
    ),
    "hostname": ShowPreset(
        key="hostname",
        command="show hostname",
        description="Configured hostname.",
        cache_tier="static",
    ),
    "clock": ShowPreset(
        key="clock",
        command="show clock",
        description="Current system clock.",
        cache_tier="realtime",
    ),
    "uptime": ShowPreset(
        key="uptime",
        command="show uptime",
        description="Controller uptime.",
        cache_tier="near_realtime",
    ),
    "boot": ShowPreset(
        key="boot",
        command="show boot",
        description="Boot partition info.",
        cache_tier="static",
    ),
    "image_version": ShowPreset(
        key="image_version",
        command="show image version",
        description="Installed image version on both partitions.",
        cache_tier="static",
    ),
}

# ---------------------------------------------------------------------------
# Domain: network  (L2/L3)
# ---------------------------------------------------------------------------
NETWORK_PRESETS: dict[str, ShowPreset] = {
    "vlan": ShowPreset(
        key="vlan",
        command="show vlan",
        description="VLAN summary.",
        normalizer="vlan",
        cache_tier="static",
    ),
    "vlan_summary": ShowPreset(
        key="vlan_summary",
        command="show vlan summary",
        description="VLAN summary counts.",
        cache_tier="static",
    ),
    "port_status": ShowPreset(
        key="port_status",
        command="show port status",
        description="Physical port status (link, speed, duplex).",
        normalizer="port_status",
        cache_tier="near_realtime",
    ),
    "port_counters": ShowPreset(
        key="port_counters",
        command="show port counters",
        description="Per-port packet counters.",
        cache_tier="realtime",
    ),
    "port_channel": ShowPreset(
        key="port_channel",
        command="show lacp port-channel",
        description="LACP port-channel state.",
        cache_tier="near_realtime",
    ),
    "ip_interface_brief": ShowPreset(
        key="ip_interface_brief",
        command="show ip interface brief",
        description="L3 interface IP/state summary.",
        normalizer="ip_interface_brief",
        cache_tier="near_realtime",
    ),
    "ip_route": ShowPreset(
        key="ip_route",
        command="show ip route",
        description="IPv4 routing table.",
        normalizer="ip_route",
        cache_tier="near_realtime",
    ),
    "ip_ospf_neighbor": ShowPreset(
        key="ip_ospf_neighbor",
        command="show ip ospf neighbor",
        description="OSPF neighbor adjacencies.",
        normalizer="ip_ospf_neighbor",
        cache_tier="near_realtime",
    ),
    "ip_ospf": ShowPreset(
        key="ip_ospf",
        command="show ip ospf",
        description="OSPF process summary.",
        cache_tier="near_realtime",
    ),
    "arp": ShowPreset(
        key="arp",
        command="show arp",
        description="ARP table.",
        normalizer="arp_table",
        cache_tier="near_realtime",
    ),
    "ip_dhcp_binding": ShowPreset(
        key="ip_dhcp_binding",
        command="show ip dhcp binding",
        description="DHCP lease bindings (controller-side DHCP).",
        cache_tier="near_realtime",
    ),
}

# ---------------------------------------------------------------------------
# Domain: aaa
# ---------------------------------------------------------------------------
AAA_PRESETS: dict[str, ShowPreset] = {
    "authentication_server_all": ShowPreset(
        key="authentication_server_all",
        command="show aaa authentication-server all",
        description="Status of every configured authentication server.",
        normalizer="aaa_servers",
        cache_tier="near_realtime",
    ),
    "server_group": ShowPreset(
        key="server_group",
        command="show aaa server-group",
        description="AAA server-group configuration.",
        cache_tier="static",
    ),
    "state_messages": ShowPreset(
        key="state_messages",
        command="show aaa state messages",
        description="Recent AAA state messages (useful for auth failures).",
        cache_tier="realtime",
    ),
    "state_debug_statistics": ShowPreset(
        key="state_debug_statistics",
        command="show aaa state debug-statistics",
        description="AAA debug counters.",
        cache_tier="realtime",
    ),
    "profile_all": ShowPreset(
        key="profile_all",
        command="show aaa profile",
        description="All AAA profiles.",
        cache_tier="static",
    ),
    "authentication_dot1x": ShowPreset(
        key="authentication_dot1x",
        command="show aaa authentication dot1x",
        description="802.1X authentication profiles.",
        cache_tier="static",
    ),
    "authentication_mac": ShowPreset(
        key="authentication_mac",
        command="show aaa authentication mac",
        description="MAC authentication profiles.",
        cache_tier="static",
    ),
    "authentication_captive_portal": ShowPreset(
        key="authentication_captive_portal",
        command="show aaa authentication captive-portal",
        description="Captive portal authentication profiles.",
        cache_tier="static",
    ),
}

# ---------------------------------------------------------------------------
# Domain: cluster / HA
# ---------------------------------------------------------------------------
CLUSTER_PRESETS: dict[str, ShowPreset] = {
    "lc_cluster_group_membership": ShowPreset(
        key="lc_cluster_group_membership",
        command="show lc-cluster group-membership",
        description="LC cluster group membership and state.",
        normalizer="lc_cluster",
        cache_tier="near_realtime",
    ),
    "lc_cluster_group_profile": ShowPreset(
        key="lc_cluster_group_profile",
        command="show lc-cluster group-profile",
        description="LC cluster group profile configuration.",
        cache_tier="static",
    ),
    "lc_cluster_vlan_probe_status": ShowPreset(
        key="lc_cluster_vlan_probe_status",
        command="show lc-cluster vlan-probe status",
        description="VLAN probe status across the cluster.",
        cache_tier="near_realtime",
    ),
    "switches_state": ShowPreset(
        key="switches_state",
        command="show switches state",
        description="State of every controller in the hierarchy.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "heartbeat": ShowPreset(
        key="heartbeat",
        command="show heartbeat",
        description="Heartbeat / keepalive status (where supported).",
        cache_tier="realtime",
    ),
    "master_redundancy": ShowPreset(
        key="master_redundancy",
        command="show master-redundancy",
        description="Conductor/master redundancy state.",
        cache_tier="near_realtime",
    ),
}

# ---------------------------------------------------------------------------
# Domain: rf  (curated RF monitoring subset)
# ---------------------------------------------------------------------------
RF_PRESETS: dict[str, ShowPreset] = {
    "arm_rf_summary": ShowPreset(
        key="arm_rf_summary",
        command="show ap arm rf-summary",
        description="Per-radio ARM RF summary (channel/power/noise) across APs.",
        normalizer="ap_radio_summary",
        cache_tier="near_realtime",
    ),
    "monitor_stats": ShowPreset(
        key="monitor_stats",
        command="show ap monitor stats",
        description="Air monitor statistics for the controller's APs.",
        normalizer="ap_monitor",
        cache_tier="near_realtime",
    ),
    "bss_table": ShowPreset(
        key="bss_table",
        command="show ap bss-table",
        description="BSSIDs of all APs registered on this controller.",
        normalizer="ap_bss_table",
        cache_tier="near_realtime",
    ),
    "radio_summary": ShowPreset(
        key="radio_summary",
        command="show ap radio-summary",
        description="Radio summary across all APs.",
        normalizer="ap_radio_summary",
        cache_tier="near_realtime",
    ),
    "radio_table": ShowPreset(
        key="radio_table",
        command="show ap radio-table",
        description="Detailed radio table.",
        cache_tier="near_realtime",
    ),
    "channel_summary": ShowPreset(
        key="channel_summary",
        command="show ap arm scan-times",
        description="ARM scan times per radio (helpful for off-channel scan tuning).",
        cache_tier="near_realtime",
    ),
}


# ---------------------------------------------------------------------------
# Registry indirection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DomainSpec:
    """Glue between a domain tool and its preset table."""

    domain: str
    default_variant: str
    presets: dict[str, ShowPreset]
    aliases: dict[str, str] = field(default_factory=dict)
    description: str = ""


DOMAINS: dict[str, DomainSpec] = {
    "controllers": DomainSpec(
        domain="controllers",
        default_variant="switches",
        presets=CONTROLLERS_PRESETS,
        description="Controller hierarchy (``show switches`` family).",
    ),
    "clients": DomainSpec(
        domain="clients",
        default_variant="global_user_table_list",
        presets=CLIENTS_PRESETS,
        description="Wireless users / user-table views.",
    ),
    "aps": DomainSpec(
        domain="aps",
        default_variant="database",
        presets=AP_PRESETS,
        aliases=_AP_ALIASES,
        description="``show ap *`` subcommands.",
    ),
    "wlan": DomainSpec(
        domain="wlan",
        default_variant="virtual_ap",
        presets=WLAN_PRESETS,
        description="``show wlan *`` subcommands and profiles.",
    ),
    "log": DomainSpec(
        domain="log",
        default_variant="all",
        presets=LOG_PRESETS,
        description="Controller log buffers (always large; prefer suffix/tail_lines).",
    ),
    "system": DomainSpec(
        domain="system",
        default_variant="version",
        presets=SYSTEM_PRESETS,
        description="Platform health and identification.",
    ),
    "network": DomainSpec(
        domain="network",
        default_variant="ip_interface_brief",
        presets=NETWORK_PRESETS,
        description="L2/L3 (VLAN, ports, IP, routing, ARP, DHCP).",
    ),
    "aaa": DomainSpec(
        domain="aaa",
        default_variant="state_messages",
        presets=AAA_PRESETS,
        description="AAA servers, profiles, and runtime state.",
    ),
    "cluster": DomainSpec(
        domain="cluster",
        default_variant="lc_cluster_group_membership",
        presets=CLUSTER_PRESETS,
        description="Cluster / HA / master redundancy.",
    ),
    "rf": DomainSpec(
        domain="rf",
        default_variant="arm_rf_summary",
        presets=RF_PRESETS,
        description="Curated RF monitoring views.",
    ),
}


def get_domain(domain: str) -> DomainSpec:
    if domain not in DOMAINS:
        raise KeyError(f"Unknown domain {domain!r}; known: {sorted(DOMAINS)}")
    return DOMAINS[domain]


def resolve_preset(domain: str, variant: str | None) -> ShowPreset:
    """Resolve a (domain, variant) pair to a registered preset.

    Falls back to ``domain.default_variant`` when ``variant`` is empty.
    """
    spec = get_domain(domain)
    key = normalize_key(variant) if variant else normalize_key(spec.default_variant)
    key = spec.aliases.get(key, key)
    if key not in spec.presets:
        choices = ", ".join(sorted(spec.presets))
        raise ValueError(
            f"Unknown variant {variant!r} for domain {domain!r}; available: {choices}"
        )
    return spec.presets[key]


def domain_catalog(domain: str) -> dict[str, dict[str, str]]:
    """``variant -> {command, description, cache_tier}`` for a single domain."""
    spec = get_domain(domain)
    return {
        k: {
            "command": p.command,
            "description": p.description,
            "cache_tier": p.cache_tier,
            "normalizer": p.normalizer,
        }
        for k, p in sorted(spec.presets.items())
    }


def full_catalog() -> dict[str, dict[str, dict[str, str]]]:
    """Top-level catalog: ``domain -> {meta, variants}``."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    for name, spec in DOMAINS.items():
        out[name] = {
            "meta": {
                "default_variant": spec.default_variant,
                "description": spec.description,
            },
            "variants": domain_catalog(name),
        }
    return out
