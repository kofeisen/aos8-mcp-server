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
    # --- show switches family (MM-side hierarchy) ----------------------
    "switches": ShowPreset(
        key="switches",
        command="show switches",
        description="All controllers (MM/MD) registered in the hierarchy.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switches_all": ShowPreset(
        key="switches_all",
        command="show switches all",
        description="Full list of all managed devices.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switches_debug": ShowPreset(
        key="switches_debug",
        command="show switches debug",
        description=(
            "Switch hierarchy with extra debug info: MAC, node-path, uptime,"
            " crash info, license, release type."
        ),
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switches_regulatory": ShowPreset(
        key="switches_regulatory",
        command="show switches regulatory",
        description="Active regulatory file (version / build) per controller.",
        normalizer="switches",
        cache_tier="static",
    ),
    "switches_summary": ShowPreset(
        key="switches_summary",
        command="show switches summary",
        description="Status summary of all managed devices.",
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
    "switches_state_complete": ShowPreset(
        key="switches_state_complete",
        command="show switches state complete",
        description="Controllers whose configuration update has completed.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switches_state_incomplete": ShowPreset(
        key="switches_state_incomplete",
        command="show switches state incomplete",
        description="Controllers whose configuration update is incomplete.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switches_state_inprogress": ShowPreset(
        key="switches_state_inprogress",
        command="show switches state inprogress",
        description="Controllers currently rolling out a configuration update.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),
    "switches_state_required": ShowPreset(
        key="switches_state_required",
        command="show switches state required",
        description="Controllers that still require a configuration update.",
        normalizer="switches",
        cache_tier="near_realtime",
    ),

    # --- local controller (the one we're logged into) -----------------
    "switch_software": ShowPreset(
        key="switch_software",
        command="show switch software",
        description=(
            "Software running on the local controller: model, ArubaOS"
            " version, build date, uptime, reboot cause, supervisor card."
        ),
        normalizer="generic",
        cache_tier="static",
    ),
    "switch_ip": ShowPreset(
        key="switch_ip",
        command="show switch ip",
        description="Local controller management IP and related parameters.",
        normalizer="generic",
        cache_tier="static",
    ),
}

# Convenience aliases for the controllers domain.
_CONTROLLERS_ALIASES: dict[str, str] = {
    "all": "switches_all",
    "debug": "switches_debug",
    "regulatory": "switches_regulatory",
    "summary": "switches_summary",
    "state_down": "switches_state_down",
    "state_complete": "switches_state_complete",
    "state_incomplete": "switches_state_incomplete",
    "state_inprogress": "switches_state_inprogress",
    "state_required": "switches_state_required",
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
#
# Every category mirrors an official ``show log <category>`` subcommand:
#   all / ap-debug / arm / arm-user-debug / errorlog / network / peer-debug
#   / security / system / user / user-debug / wireless
# The trailing ``all`` keyword pulls in rotated files (e.g., security log +
# security.1, security.2, ...). aos8_log also supports a device-side
# ``tail=<N>`` parameter that appends ``<N>`` to the CLI so the controller
# itself trims to the last N lines — much cheaper than fetching the full
# buffer and trimming server-side.
# ---------------------------------------------------------------------------
LOG_PRESETS: dict[str, ShowPreset] = {
    "all": ShowPreset(
        key="all",
        command="show log all",
        description=(
            "Full controller log buffer across every category. Large by"
            " default — use tail=<N> for device-side tail and / or"
            " cli_suffix / match=<token> for grep-style filtering."
        ),
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
        description="Security log entries (auth, captive portal, role transitions).",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "system": ShowPreset(
        key="system",
        command="show log system all",
        description="System log entries.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "user": ShowPreset(
        key="user",
        command="show log user all",
        description="User-facing log entries (association, authentication).",
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
    "ap_debug": ShowPreset(
        key="ap_debug",
        command="show log ap-debug all",
        description="AP-side debug logs collected by the controller.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "arm": ShowPreset(
        key="arm",
        command="show log arm all",
        description="ARM (Adaptive Radio Management) log entries.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "arm_user_debug": ShowPreset(
        key="arm_user_debug",
        command="show log arm-user-debug all",
        description="ARM user-debug log entries (per-client RF debug capture).",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "network": ShowPreset(
        key="network",
        command="show log network all",
        description="Network subsystem log entries (routing, interfaces, ARP).",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "peer_debug": ShowPreset(
        key="peer_debug",
        command="show log peer-debug all",
        description="Peer / cluster debug log entries.",
        normalizer="log_text",
        cache_tier="realtime",
    ),
    "user_debug": ShowPreset(
        key="user_debug",
        command="show log user-debug all",
        description=(
            "User debug log entries (set by ``logging level debugging user mac/ip ...``)."
        ),
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
        description="Controller software/hardware version (short banner).",
        cache_tier="static",
    ),
    "switchinfo": ShowPreset(
        key="switchinfo",
        command="show switchinfo",
        description=(
            "Comprehensive local-controller identity dump: hostname, system"
            " time, OS version, uptime, reboot cause, management IP, switch"
            " role and save/crash status. Single-call platform snapshot."
        ),
        cache_tier="near_realtime",
    ),
    "switch_software": ShowPreset(
        key="switch_software",
        command="show switch software",
        description=(
            "Software running on the local controller (model, ArubaOS version,"
            " build date, uptime, reboot cause, supervisor card)."
        ),
        cache_tier="static",
    ),
    "switch_ip": ShowPreset(
        key="switch_ip",
        command="show switch ip",
        description="Local controller management IP and related parameters.",
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
    "authentication_dot1x_countermeasures": ShowPreset(
        key="authentication_dot1x_countermeasures",
        command="show aaa authentication dot1x countermeasures",
        description="802.1X anti-cloning / countermeasure runtime view.",
        cache_tier="near_realtime",
    ),
    "authentication_stateful_dot1x": ShowPreset(
        key="authentication_stateful_dot1x",
        command="show aaa authentication stateful-dot1x",
        description="Stateful 802.1X session summary.",
        cache_tier="near_realtime",
    ),
    "authentication_stateful_dot1x_config_entries": ShowPreset(
        key="authentication_stateful_dot1x_config_entries",
        command="show aaa authentication stateful-dot1x config-entries",
        description="Stateful 802.1X profile configuration entries.",
        cache_tier="static",
    ),
    "authentication_server_radius": ShowPreset(
        key="authentication_server_radius",
        command="show aaa authentication-server radius",
        description=(
            "Configured RADIUS servers; pass arg=<server-name> for a single server "
            "(CLI-Bank: show aaa authentication-server radius <name>)."
        ),
        normalizer="aaa_servers",
        cache_tier="near_realtime",
    ),
    "authentication_server_radius_statistics": ShowPreset(
        key="authentication_server_radius_statistics",
        command="show aaa authentication-server radius statistics",
        description="RADIUS request/response statistics.",
        cache_tier="near_realtime",
    ),
    "authentication_server_radius_radsec_status": ShowPreset(
        key="authentication_server_radius_radsec_status",
        command="show aaa authentication-server radius radsec status",
        description="RadSec (TLS) session status for RADIUS.",
        cache_tier="near_realtime",
    ),
}

_AAA_ALIASES: dict[str, str] = {
    "auth_servers": "authentication_server_all",
    "servers_all": "authentication_server_all",
    "radius": "authentication_server_radius",
    "radius_servers": "authentication_server_radius",
    "radius_statistics": "authentication_server_radius_statistics",
    "radius_radsec": "authentication_server_radius_radsec_status",
    "radius_radsec_status": "authentication_server_radius_radsec_status",
    "dot1x": "authentication_dot1x",
    "mac_auth": "authentication_mac",
    "cp": "authentication_captive_portal",
    "captive": "authentication_captive_portal",
    "stateful_dot1x": "authentication_stateful_dot1x",
    "stateful_dot1x_config": "authentication_stateful_dot1x_config_entries",
    "dot1x_countermeasures": "authentication_dot1x_countermeasures",
}

# ---------------------------------------------------------------------------
# Domain: cluster / HA
#
# Almost every ``show lc-cluster *`` and ``show datapath cluster *`` command
# is documented as "Config mode or enable mode in the managed device", which
# means MM/Conductor returns "not applicable on conductor". The aos8_cluster
# tool dispatches lc-cluster / datapath cluster presets directly to an MD to
# avoid a wasted MM round trip; ``switches_state`` / ``heartbeat`` /
# ``master_redundancy`` remain MM-runnable and use the standard MM-then-MD
# fallback.
# ---------------------------------------------------------------------------
CLUSTER_PRESETS: dict[str, ShowPreset] = {
    # --- group / membership / profile ---------------------------------
    "lc_cluster_group_membership": ShowPreset(
        key="lc_cluster_group_membership",
        command="show lc-cluster group-membership",
        description=(
            "Active cluster members and state (Leader/Member/Incompatible) "
            "with peer IPs and connection-type."
        ),
        normalizer="lc_cluster",
        cache_tier="near_realtime",
    ),
    "lc_cluster_group_profile": ShowPreset(
        key="lc_cluster_group_profile",
        command="show lc-cluster group-profile",
        description=(
            "LC cluster group profile (members, priority, MCAST/VRRP VLAN, "
            "RAP public IP). Pass arg=<profile-name> for a single profile."
        ),
        cache_tier="static",
    ),

    # --- vlan probe / exclude -----------------------------------------
    "lc_cluster_exclude_vlan": ShowPreset(
        key="lc_cluster_exclude_vlan",
        command="show lc-cluster exclude-vlan",
        description="VLANs excluded from L2 probing.",
        cache_tier="static",
    ),
    "lc_cluster_vlan_probe_status": ShowPreset(
        key="lc_cluster_vlan_probe_status",
        command="show lc-cluster vlan-probe status",
        description="VLAN probe status across the cluster (REQ/ACK/FAIL counters per peer).",
        cache_tier="near_realtime",
    ),

    # --- heartbeat / control-plane counters ---------------------------
    "lc_cluster_heartbeat_counters": ShowPreset(
        key="lc_cluster_heartbeat_counters",
        command="show lc-cluster heartbeat counters",
        description=(
            "Per-peer heartbeat counters (RES/RSR/MIS/HMPD/LMRPD/IDPD/CPDPD/"
            "CDPD/LMHINT/LTOD) — primary signal for peer disconnect events."
        ),
        cache_tier="realtime",
    ),
    "lc_cluster_papi_counters": ShowPreset(
        key="lc_cluster_papi_counters",
        command="show lc-cluster papi counters",
        description="Cluster control-plane PAPI messaging counters.",
        cache_tier="realtime",
    ),
    "lc_cluster_gsm_counters": ShowPreset(
        key="lc_cluster_gsm_counters",
        command="show lc-cluster gsm counters",
        description="Cluster GSM (Global State Machine) counters across STA/AP/BSS channels.",
        cache_tier="realtime",
    ),

    # --- history / events ---------------------------------------------
    "lc_cluster_history": ShowPreset(
        key="lc_cluster_history",
        command="show lc-cluster history",
        description="Cluster connect/disconnect history with reason and timestamp.",
        cache_tier="realtime",
    ),
    "lc_cluster_global_events": ShowPreset(
        key="lc_cluster_global_events",
        command="show lc-cluster global-events",
        description="Cluster global events.",
        cache_tier="realtime",
    ),

    # --- load distribution -------------------------------------------
    "lc_cluster_load_distribution_ap": ShowPreset(
        key="lc_cluster_load_distribution_ap",
        command="show lc-cluster load distribution ap",
        description="AP load distribution across cluster members (Active/Standby APs per node).",
        cache_tier="near_realtime",
    ),
    "lc_cluster_load_distribution_client": ShowPreset(
        key="lc_cluster_load_distribution_client",
        command="show lc-cluster load distribution client",
        description="Client load distribution across cluster members.",
        cache_tier="near_realtime",
    ),

    # --- bucket map / distribution (8.11+) ----------------------------
    "lc_cluster_bucket_distribution_all": ShowPreset(
        key="lc_cluster_bucket_distribution_all",
        command="show lc-cluster bucket distribution all",
        description="Current bucket distribution for all ESSIDs (AOS 8.11+).",
        cache_tier="near_realtime",
    ),
    "lc_cluster_bucket_distribution_essid": ShowPreset(
        key="lc_cluster_bucket_distribution_essid",
        command="show lc-cluster bucket distribution essid",
        description="Current bucket distribution for a specific ESSID — pass arg=<essid>.",
        cache_tier="near_realtime",
    ),
    "lc_cluster_bucketmap_publish_counters": ShowPreset(
        key="lc_cluster_bucketmap_publish_counters",
        command="show lc-cluster bucketmap publish counters",
        description="Bucketmap publish counters (AOS 8.11+).",
        cache_tier="realtime",
    ),

    # --- upgrade ------------------------------------------------------
    "lc_cluster_upgrade": ShowPreset(
        key="lc_cluster_upgrade",
        command="show lc-cluster upgrade",
        description="Cluster upgrade overview (per-controller and per-AP status).",
        cache_tier="near_realtime",
    ),
    "lc_cluster_scheduled_upgrades": ShowPreset(
        key="lc_cluster_scheduled_upgrades",
        command="show lc-cluster scheduled-upgrades",
        description="Status of clusters scheduled for upgrade.",
        cache_tier="near_realtime",
    ),

    # --- datapath cluster (forwarding-plane HA view) ------------------
    "datapath_cluster": ShowPreset(
        key="datapath_cluster",
        command="show datapath cluster",
        description="Datapath cluster statistics (forwarding-plane HA view).",
        cache_tier="realtime",
    ),
    "datapath_cluster_details": ShowPreset(
        key="datapath_cluster_details",
        command="show datapath cluster details",
        description=(
            "Datapath cluster heartbeat data: thresholds, datapath assignments, "
            "per-peer HBT counters (Sent/Rcvd/Inflight/Drops). "
            "Pass arg='peer <ip>' to scope to one peer."
        ),
        cache_tier="realtime",
    ),
    "datapath_cluster_heartbeat_counters": ShowPreset(
        key="datapath_cluster_heartbeat_counters",
        command="show datapath cluster heartbeat counters",
        description="Datapath cluster heartbeat counters.",
        cache_tier="realtime",
    ),

    # --- generic / cross-domain helpers (run on MM) -------------------
    "switches_state": ShowPreset(
        key="switches_state",
        command="show switches state",
        description="State of every controller in the hierarchy (MM-side view).",
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

# Convenience aliases so callers can use familiar shorter names.
_CLUSTER_ALIASES: dict[str, str] = {
    "group_membership": "lc_cluster_group_membership",
    "group_profile": "lc_cluster_group_profile",
    "heartbeat_counters": "lc_cluster_heartbeat_counters",
    "history": "lc_cluster_history",
    "global_events": "lc_cluster_global_events",
    "vlan_probe_status": "lc_cluster_vlan_probe_status",
    "load_ap": "lc_cluster_load_distribution_ap",
    "load_client": "lc_cluster_load_distribution_client",
    "papi_counters": "lc_cluster_papi_counters",
    "gsm_counters": "lc_cluster_gsm_counters",
    "upgrade": "lc_cluster_upgrade",
    "scheduled_upgrades": "lc_cluster_scheduled_upgrades",
    "exclude_vlan": "lc_cluster_exclude_vlan",
    "bucket_all": "lc_cluster_bucket_distribution_all",
    "bucket_essid": "lc_cluster_bucket_distribution_essid",
    "bucketmap_publish_counters": "lc_cluster_bucketmap_publish_counters",
    "dp_cluster": "datapath_cluster",
    "dp_cluster_details": "datapath_cluster_details",
    "dp_cluster_heartbeat_counters": "datapath_cluster_heartbeat_counters",
}

# ---------------------------------------------------------------------------
# Domain: rf
#
# Two families:
#   * Operational monitoring — ``show ap arm …``, ``show ap monitor …``, radio tables.
#   * RF configuration (official ``show rf`` umbrella — Mobility Conductor) —
#     AM scan / ARM / radio profiles / spectrum / optimization / thresholds.
# ---------------------------------------------------------------------------
RF_PRESETS: dict[str, ShowPreset] = {
    # --- operational monitoring ----------------------------------------
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

    # --- show rf <profile> (AOS 8 CLI-Bank sh-rf.htm) --------------------
    "rf_am_scan_profile": ShowPreset(
        key="rf_am_scan_profile",
        command="show rf am-scan-profile",
        description="Air Monitor (AM) scanning profile configuration.",
        cache_tier="static",
    ),
    "rf_arm_profile": ShowPreset(
        key="rf_arm_profile",
        command="show rf arm-profile",
        description="Adaptive Radio Management (ARM) profile configuration.",
        cache_tier="static",
    ),
    "rf_arm_rf_domain_profile": ShowPreset(
        key="rf_arm_rf_domain_profile",
        command="show rf arm-rf-domain-profile",
        description="ARM RF domain profile.",
        cache_tier="static",
    ),
    "rf_dot11_60ghz_radio_profile": ShowPreset(
        key="rf_dot11_60ghz_radio_profile",
        command="show rf dot11-60GHz-radio-profile",
        description="802.11ad / 60 GHz radio profile.",
        cache_tier="static",
    ),
    "rf_dot11_6ghz_radio_profile": ShowPreset(
        key="rf_dot11_6ghz_radio_profile",
        command="show rf dot11-6GHz-radio-profile",
        description="802.11ax 6 GHz radio profile.",
        cache_tier="static",
    ),
    "rf_dot11a_radio_profile": ShowPreset(
        key="rf_dot11a_radio_profile",
        command="show rf dot11a-radio-profile",
        description="802.11a/5 GHz radio profile.",
        cache_tier="static",
    ),
    "rf_dot11a_secondary_radio_profile": ShowPreset(
        key="rf_dot11a_secondary_radio_profile",
        command="show rf dot11a-secondary-radio-profile",
        description="802.11a secondary radio profile.",
        cache_tier="static",
    ),
    "rf_dot11g_radio_profile": ShowPreset(
        key="rf_dot11g_radio_profile",
        command="show rf dot11g-radio-profile",
        description="802.11b/g/2.4 GHz radio profile.",
        cache_tier="static",
    ),
    "rf_event_thresholds_profile": ShowPreset(
        key="rf_event_thresholds_profile",
        command="show rf event-thresholds-profile",
        description="RF event thresholds profile.",
        cache_tier="static",
    ),
    "rf_ht_radio_profile": ShowPreset(
        key="rf_ht_radio_profile",
        command="show rf ht-radio-profile",
        description="802.11n high-throughput radio profile.",
        cache_tier="static",
    ),
    "rf_optimization_profile": ShowPreset(
        key="rf_optimization_profile",
        command="show rf optimization-profile",
        description="RF optimization profile.",
        cache_tier="static",
    ),
    "rf_spectrum_profile": ShowPreset(
        key="rf_spectrum_profile",
        command="show rf spectrum-profile",
        description="Spectrum analysis profile.",
        cache_tier="static",
    ),
}

_RF_ALIASES: dict[str, str] = {
    # Map hyphenated doc names / short forms to canonical preset keys.
    "rf_summary": "arm_rf_summary",
    "am_scan_profile": "rf_am_scan_profile",
    "arm_profile": "rf_arm_profile",
    "arm_rf_domain_profile": "rf_arm_rf_domain_profile",
    "dot11_60ghz_radio_profile": "rf_dot11_60ghz_radio_profile",
    "dot11_6ghz_radio_profile": "rf_dot11_6ghz_radio_profile",
    "dot11a_radio_profile": "rf_dot11a_radio_profile",
    "dot11a_secondary_radio_profile": "rf_dot11a_secondary_radio_profile",
    "dot11g_radio_profile": "rf_dot11g_radio_profile",
    "event_thresholds_profile": "rf_event_thresholds_profile",
    "ht_radio_profile": "rf_ht_radio_profile",
    "optimization_profile": "rf_optimization_profile",
    "spectrum_profile": "rf_spectrum_profile",
}


# ---------------------------------------------------------------------------
# Domain: airmatch  (AirMatch RF automation — ``show airmatch …``)
#
# Commands run on Mobility Conductor (enable/config). Use ``arg`` for trailing
# tokens (optimization sequence number, ``band 5 GHz``, ``mac <mac>``,
# ``switch-ip <ip>``, ``sort-by …``, ``advanced partition``, ``last``, etc.).
# ---------------------------------------------------------------------------
AIRMATCH_PRESETS: dict[str, ShowPreset] = {
    "profile": ShowPreset(
        key="profile",
        command="show airmatch profile",
        description=(
            "AirMatch profile: schedule, deploy-hour, quality-threshold, etc."
        ),
        cache_tier="static",
    ),
    "optimization": ShowPreset(
        key="optimization",
        command="show airmatch optimization",
        description=(
            "Recent AirMatch optimization jobs; append arg=<seq> for per-radio"
            " channel/EIRP plan for that solution."
        ),
        cache_tier="near_realtime",
    ),
    "solution_list_all": ShowPreset(
        key="solution_list_all",
        command="show airmatch solution list-all",
        description="AirMatch solution history for all radios (band, radio MAC, chan, EIRP, AP name).",
        cache_tier="near_realtime",
    ),
    "solution": ShowPreset(
        key="solution",
        command="show airmatch solution",
        description=(
            "AirMatch solution scoped by AP/radio/switch. Pass ap_name=… or"
            " arg='band 5 GHz' / 'mac <radiomac>' / 'switch-ip <ip>'."
        ),
        cache_tier="near_realtime",
    ),
    "ap_partition_status_detail": ShowPreset(
        key="ap_partition_status_detail",
        command="show airmatch ap-partition status detail",
        description="Cluster-manager AP partition status (detail).",
        cache_tier="near_realtime",
    ),
    "debug_apinfo": ShowPreset(
        key="debug_apinfo",
        command="show airmatch debug apinfo",
        description=(
            "AirMatch debug snapshot for an AP. Pass ap_name=… or"
            " arg='ethmac …' / 'radiomac …'."
        ),
        cache_tier="near_realtime",
    ),
    "debug_history": ShowPreset(
        key="debug_history",
        command="show airmatch debug history",
        description=(
            "Channel/bandwidth/EIRP/mode change history for an AP radio."
            " Pass ap_name=… or arg='mac <radiomac>'."
        ),
        cache_tier="near_realtime",
    ),
    "debug_db_dump_status": ShowPreset(
        key="debug_db_dump_status",
        command="show airmatch debug db-dump status",
        description="Status of the AirMatch debug DB dump (SUCCESS/fail, timestamps).",
        cache_tier="near_realtime",
    ),
    "debug_optimization": ShowPreset(
        key="debug_optimization",
        command="show airmatch debug optimization",
        description=(
            "Debug view of AirMatch optimizations; arg examples: 'last', "
            "'77', 'advanced partition', '77 sort-by ap-name descending'."
        ),
        cache_tier="near_realtime",
    ),
    "debug_client_history": ShowPreset(
        key="debug_client_history",
        command="show airmatch debug client-history",
        description="AirMatch client-count debug for an AP (ap_name or arg='mac …').",
        cache_tier="near_realtime",
    ),
}

_AIRMATCH_ALIASES: dict[str, str] = {
    "opt": "optimization",
    "solution_all": "solution_list_all",
    "partition": "ap_partition_status_detail",
    "ap_partition": "ap_partition_status_detail",
    "db_dump_status": "debug_db_dump_status",
    "dbg_opt": "debug_optimization",
    "dbg_apinfo": "debug_apinfo",
    "dbg_history": "debug_history",
    "dbg_client_history": "debug_client_history",
}


# ---------------------------------------------------------------------------
# Domain: datapath  (forwarding-plane diagnostics — ``show datapath *``)
#
# Almost every datapath subcommand is realtime: counters / tables that change
# on every packet. We therefore default the cache tier to ``realtime`` (TTL=0)
# so callers always see fresh state during a troubleshooting session.
# ---------------------------------------------------------------------------
DATAPATH_PRESETS: dict[str, ShowPreset] = {
    # --- bridge family --------------------------------------------------
    "bridge": ShowPreset(
        key="bridge",
        command="show datapath bridge",
        description="Bridge table snapshot. Use ap_name / ip_addr to scope to one AP.",
        cache_tier="realtime",
    ),
    "bridge_counters": ShowPreset(
        key="bridge_counters",
        command="show datapath bridge counters",
        description="Bridge table counters (entries, water mark, allocation failures, max link length).",
        cache_tier="realtime",
    ),
    "bridge_devices": ShowPreset(
        key="bridge_devices",
        command="show datapath bridge devices",
        description="Datapath bridge devices.",
        cache_tier="realtime",
    ),
    "bridge_table": ShowPreset(
        key="bridge_table",
        command="show datapath bridge table",
        description="Bridge table — pass arg=<macaddr> to look up a single MAC.",
        cache_tier="realtime",
    ),
    "bridge_verbose": ShowPreset(
        key="bridge_verbose",
        command="show datapath bridge verbose",
        description="Bridge details in tabular format.",
        cache_tier="realtime",
    ),

    # --- cluster family -------------------------------------------------
    "cluster": ShowPreset(
        key="cluster",
        command="show datapath cluster",
        description="Datapath cluster statistics (controller HA forwarding view).",
        cache_tier="realtime",
    ),
    "cluster_details": ShowPreset(
        key="cluster_details",
        command="show datapath cluster details",
        description="Detailed heartbeat counters with missed/delayed sequence numbers.",
        cache_tier="realtime",
    ),
    "cluster_heartbeat_counters": ShowPreset(
        key="cluster_heartbeat_counters",
        command="show datapath cluster heartbeat counters",
        description="Cluster heartbeat counters.",
        cache_tier="realtime",
    ),

    # --- session family -------------------------------------------------
    "session": ShowPreset(
        key="session",
        command="show datapath session",
        description=(
            "Datapath session table snapshot. Use ap_name / ip_addr to scope. "
            "Output can be very large; consider max_rows or cli_suffix='| include ...'."
        ),
        cache_tier="realtime",
    ),
    "session_table": ShowPreset(
        key="session_table",
        command="show datapath session table",
        description="Datapath session table; pass arg=<A.B.C.D> to filter by IP.",
        cache_tier="realtime",
    ),
    "session_counters": ShowPreset(
        key="session_counters",
        command="show datapath session counters",
        description="Session counters: current/high/max entries, aged, pending deletes.",
        cache_tier="realtime",
    ),
    "session_dpi": ShowPreset(
        key="session_dpi",
        command="show datapath session dpi",
        description="DPI session view (top level).",
        cache_tier="realtime",
    ),
    "session_dpi_counters": ShowPreset(
        key="session_dpi_counters",
        command="show datapath session dpi counters",
        description="DPI session counters; pass arg='top' or 'all' for variants.",
        cache_tier="realtime",
    ),
    "session_dpi_table": ShowPreset(
        key="session_dpi_table",
        command="show datapath session dpi table",
        description="DPI session table; pass arg=<A.B.C.D> or 'appid <id>'.",
        cache_tier="realtime",
    ),
    "session_high_value": ShowPreset(
        key="session_high_value",
        command="show datapath session high-value",
        description="High-value sessions; pass arg='user <macaddr>' to filter by user.",
        cache_tier="realtime",
    ),
    "session_session_id": ShowPreset(
        key="session_session_id",
        command="show datapath session session-id",
        description="Look up a session by id; pass arg=<sid> (optionally append 'dpi').",
        cache_tier="realtime",
    ),
    "session_uplink": ShowPreset(
        key="session_uplink",
        command="show datapath session uplink",
        description="Sessions associated with the uplink VLAN.",
        cache_tier="realtime",
    ),
    "session_perf": ShowPreset(
        key="session_perf",
        command="show datapath session perf",
        description="Session performance metrics.",
        cache_tier="realtime",
    ),
    "session_ipv6": ShowPreset(
        key="session_ipv6",
        command="show datapath session ipv6",
        description="IPv6 datapath sessions.",
        cache_tier="realtime",
    ),

    # --- tunnel family --------------------------------------------------
    "tunnel": ShowPreset(
        key="tunnel",
        command="show datapath tunnel",
        description=(
            "Datapath tunnel table (GRE for APs, IPsec, etc.). "
            "Includes Source/Destination, Type, MTU, VLAN, Decap/Encap and Heartbeats."
        ),
        cache_tier="realtime",
    ),
    "tunnel_table": ShowPreset(
        key="tunnel_table",
        command="show datapath tunnel table",
        description="Datapath tunnel table summary.",
        cache_tier="realtime",
    ),
    "tunnel_counters": ShowPreset(
        key="tunnel_counters",
        command="show datapath tunnel counters",
        description="Tunnel counters / FIB stats / entry water marks.",
        cache_tier="realtime",
    ),
    "tunnel_encaps": ShowPreset(
        key="tunnel_encaps",
        command="show datapath tunnel encaps",
        description="Per-tunnel encapsulation statistics.",
        cache_tier="realtime",
    ),
    "tunnel_heartbeat": ShowPreset(
        key="tunnel_heartbeat",
        command="show datapath tunnel heartbeat",
        description="Tunnel heartbeat statistics.",
        cache_tier="realtime",
    ),
    "tunnel_ipv4": ShowPreset(
        key="tunnel_ipv4",
        command="show datapath tunnel ipv4",
        description="IPv4 tunnel table entries.",
        cache_tier="realtime",
    ),
    "tunnel_ipv6": ShowPreset(
        key="tunnel_ipv6",
        command="show datapath tunnel ipv6",
        description="IPv6 tunnel table entries (incl. L2 GRE for IPv6).",
        cache_tier="realtime",
    ),
    "tunnel_station_list": ShowPreset(
        key="tunnel_station_list",
        command="show datapath tunnel station-list",
        description="Tunnel-bound station list.",
        cache_tier="realtime",
    ),
    "tunnel_id": ShowPreset(
        key="tunnel_id",
        command="show datapath tunnel tunnel-id",
        description=(
            "Detail for a specific tunnel; pass arg=<tid> "
            "(optionally append 'trusted-vlan' or 'untrusted-vlan')."
        ),
        cache_tier="realtime",
    ),
    "tunnel_verbose": ShowPreset(
        key="tunnel_verbose",
        command="show datapath tunnel verbose",
        description="Tunnel table verbose view.",
        cache_tier="realtime",
    ),

    # --- user family ----------------------------------------------------
    "user": ShowPreset(
        key="user",
        command="show datapath user",
        description="Datapath user table top-level (use ap_name / ip_addr to scope).",
        cache_tier="realtime",
    ),
    "user_table": ShowPreset(
        key="user_table",
        command="show datapath user table",
        description="Datapath user table.",
        cache_tier="realtime",
    ),
    "user_all": ShowPreset(
        key="user_all",
        command="show datapath user all",
        description="Datapath user table for all CPUs.",
        cache_tier="realtime",
    ),
    "user_counters": ShowPreset(
        key="user_counters",
        command="show datapath user counters",
        description="Datapath user counters (current/high/max, allocation failures).",
        cache_tier="realtime",
    ),
    "user_ipv4": ShowPreset(
        key="user_ipv4",
        command="show datapath user ipv4",
        description="Datapath IPv4 user view.",
        cache_tier="realtime",
    ),
    "user_ipv6": ShowPreset(
        key="user_ipv6",
        command="show datapath user ipv6",
        description="Datapath IPv6 user view.",
        cache_tier="realtime",
    ),
    "user_verbose": ShowPreset(
        key="user_verbose",
        command="show datapath user verbose",
        description="Datapath user verbose view.",
        cache_tier="realtime",
    ),

    # --- vlan family ----------------------------------------------------
    "vlan": ShowPreset(
        key="vlan",
        command="show datapath vlan",
        description="VLAN membership inside the datapath (incl. L2 tunnels).",
        cache_tier="realtime",
    ),
    "vlan_table": ShowPreset(
        key="vlan_table",
        command="show datapath vlan table",
        description="Datapath VLAN table (VLAN / Flags / RACL / Ports).",
        cache_tier="realtime",
    ),
    "vlan_pvst": ShowPreset(
        key="vlan_pvst",
        command="show datapath vlan pvst",
        description="Datapath PVST per-VLAN STP state.",
        cache_tier="realtime",
    ),

    # --- frame family ---------------------------------------------------
    "frame": ShowPreset(
        key="frame",
        command="show datapath frame",
        description=(
            "High-level packet processing counters (allocated frames, flood frames, "
            "IP fragmentation/reassembly, BPDUs)."
        ),
        cache_tier="realtime",
    ),
    "frame_counters": ShowPreset(
        key="frame_counters",
        command="show datapath frame counters",
        description=(
            "Detailed per-frame counters: Rx/Tx frames+bytes, denied frames, "
            "Dot1d/Dot1Q discards, etc."
        ),
        cache_tier="realtime",
    ),

    # --- crypto family --------------------------------------------------
    "crypto": ShowPreset(
        key="crypto",
        command="show datapath crypto",
        description="Datapath crypto top-level snapshot.",
        cache_tier="realtime",
    ),
    "crypto_counters": ShowPreset(
        key="crypto_counters",
        command="show datapath crypto counters",
        description="Crypto counters (IPsec, dot1x term, RSA, AESCCM).",
        cache_tier="realtime",
    ),

    # --- route / route-cache -------------------------------------------
    "route": ShowPreset(
        key="route",
        command="show datapath route",
        description="Datapath route table snapshot.",
        cache_tier="realtime",
    ),
    "route_table": ShowPreset(
        key="route_table",
        command="show datapath route table",
        description="Datapath route table.",
        cache_tier="realtime",
    ),
    "route_counters": ShowPreset(
        key="route_counters",
        command="show datapath route counters",
        description="Datapath route counters.",
        cache_tier="realtime",
    ),
    "route_cache": ShowPreset(
        key="route_cache",
        command="show datapath route-cache",
        description="Datapath route-cache snapshot.",
        cache_tier="realtime",
    ),
    "route_cache_table": ShowPreset(
        key="route_cache_table",
        command="show datapath route-cache table",
        description="Datapath route-cache table.",
        cache_tier="realtime",
    ),
    "route_cache_counters": ShowPreset(
        key="route_cache_counters",
        command="show datapath route-cache counters",
        description="Datapath route-cache counters.",
        cache_tier="realtime",
    ),

    # --- nat ------------------------------------------------------------
    "nat": ShowPreset(
        key="nat",
        command="show datapath nat",
        description="Datapath NAT table snapshot.",
        cache_tier="realtime",
    ),
    "nat_table": ShowPreset(
        key="nat_table",
        command="show datapath nat table",
        description="Datapath NAT table.",
        cache_tier="realtime",
    ),

    # --- mobility (datapath mobility tables for L3 roaming) ------------
    "mobility_discovery_table": ShowPreset(
        key="mobility_discovery_table",
        command="show datapath mobility discovery-table",
        description="Per-client home-agent discovery counts.",
        cache_tier="realtime",
    ),
    "mobility_home_agent_table": ShowPreset(
        key="mobility_home_agent_table",
        command="show datapath mobility home-agent-table",
        description="Home-agent table for L3 mobility.",
        cache_tier="realtime",
    ),
    "mobility_mcast_table": ShowPreset(
        key="mobility_mcast_table",
        command="show datapath mobility mcast-table",
        description="Multicast group table that floods RA traffic to roamed clients.",
        cache_tier="realtime",
    ),
    "mobility_stats": ShowPreset(
        key="mobility_stats",
        command="show datapath mobility stats",
        description="Datapath mobility statistics (HA discovery, HAT insert/delete).",
        cache_tier="realtime",
    ),

    # --- station --------------------------------------------------------
    "station": ShowPreset(
        key="station",
        command="show datapath station",
        description="Datapath station table top-level.",
        cache_tier="realtime",
    ),
    "station_table": ShowPreset(
        key="station_table",
        command="show datapath station table",
        description="Datapath station table.",
        cache_tier="realtime",
    ),
    "station_counters": ShowPreset(
        key="station_counters",
        command="show datapath station counters",
        description="Datapath station counters.",
        cache_tier="realtime",
    ),

    # --- hardware -------------------------------------------------------
    "hardware_counters": ShowPreset(
        key="hardware_counters",
        command="show datapath hardware counters",
        description="Hardware counters from the datapath ASIC/CPU.",
        cache_tier="realtime",
    ),
    "hardware_statistics": ShowPreset(
        key="hardware_statistics",
        command="show datapath hardware statistics",
        description="Hardware statistics block.",
        cache_tier="realtime",
    ),

    # --- debug ----------------------------------------------------------
    "debug_performance": ShowPreset(
        key="debug_performance",
        command="show datapath debug performance",
        description="Datapath debug performance snapshot per CPU.",
        cache_tier="realtime",
    ),
    "debug_performance_counters": ShowPreset(
        key="debug_performance_counters",
        command="show datapath debug performance counters",
        description="Datapath debug performance counters.",
        cache_tier="realtime",
    ),
    "debug_dma_counters": ShowPreset(
        key="debug_dma_counters",
        command="show datapath debug dma counters",
        description="Datapath DMA debug counters.",
        cache_tier="realtime",
    ),
    "debug_eap_counters": ShowPreset(
        key="debug_eap_counters",
        command="show datapath debug eap counters",
        description="EAP termination debug counters.",
        cache_tier="realtime",
    ),

    # --- compression ----------------------------------------------------
    "compression": ShowPreset(
        key="compression",
        command="show datapath compression",
        description="Datapath compression statistics.",
        cache_tier="realtime",
    ),
    "compression_counters": ShowPreset(
        key="compression_counters",
        command="show datapath compression counters",
        description="Datapath compression counters.",
        cache_tier="realtime",
    ),

    # --- IP fragmentation / reassembly ---------------------------------
    "ip_fragment_table": ShowPreset(
        key="ip_fragment_table",
        command="show datapath ip-fragment-table",
        description="IP fragment table; pass arg='ipv4' or 'ipv6' to scope.",
        cache_tier="realtime",
    ),
    "ip_reassembly": ShowPreset(
        key="ip_reassembly",
        command="show datapath ip-reassembly",
        description="IP reassembly stats; pass arg='counters' / 'ipv4' / 'ipv6'.",
        cache_tier="realtime",
    ),

    # --- exception / error / heartbeat ---------------------------------
    "exception_counters": ShowPreset(
        key="exception_counters",
        command="show datapath exception counters",
        description="Datapath exception counters.",
        cache_tier="realtime",
    ),
    "error_counters": ShowPreset(
        key="error_counters",
        command="show datapath error counters",
        description="Datapath error counters.",
        cache_tier="realtime",
    ),
    "heartbeat_stats": ShowPreset(
        key="heartbeat_stats",
        command="show datapath heartbeat stats",
        description="Datapath heartbeat stats (controller-side).",
        cache_tier="realtime",
    ),
    "utilization": ShowPreset(
        key="utilization",
        command="show datapath utilization",
        description=(
            "Per-datapath-CPU utilization by CPU ID (1 s, 4 s, and 64 s windows). "
            "Primary CLI for datapath forwarding-plane CPU load (CLI-Bank: utilization)."
        ),
        cache_tier="realtime",
    ),

    # --- acl / ipsec-map / misc ---------------------------------------
    "acl": ShowPreset(
        key="acl",
        command="show datapath acl",
        description="Datapath ACL entries (resolved against role/session ACLs).",
        cache_tier="realtime",
    ),
    "ipsec_map": ShowPreset(
        key="ipsec_map",
        command="show datapath ipsec-map",
        description="Datapath IPsec map (per-tunnel SA mapping).",
        cache_tier="realtime",
    ),
    "outstanding_buffers": ShowPreset(
        key="outstanding_buffers",
        command="show datapath outstanding-buffers",
        description="Outstanding buffer count per CPU.",
        cache_tier="realtime",
    ),
    "papi_counters": ShowPreset(
        key="papi_counters",
        command="show datapath papi counters",
        description="PAPI control-plane counters.",
        cache_tier="realtime",
    ),
}

# Convenience aliases for ergonomic variant names.
_DATAPATH_ALIASES: dict[str, str] = {
    "tunnels": "tunnel",
    "sessions": "session",
    "users": "user",
    "vlans": "vlan",
    "cpu": "utilization",
    "cpu_utilization": "utilization",
    "datapath_cpu": "utilization",
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
        aliases=_CONTROLLERS_ALIASES,
        description="Controller hierarchy (``show switches`` family + local-controller info).",
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
        aliases=_AAA_ALIASES,
        description=(
            "AAA authentication servers, profiles, and runtime state "
            "(``show aaa authentication-server …``, ``show aaa authentication …``, "
            "``show aaa state …``)."
        ),
    ),
    "cluster": DomainSpec(
        domain="cluster",
        default_variant="lc_cluster_group_membership",
        presets=CLUSTER_PRESETS,
        aliases=_CLUSTER_ALIASES,
        description=(
            "Cluster / HA / master redundancy. Most ``show lc-cluster *`` and"
            " ``show datapath cluster *`` commands run on MD; aos8_cluster"
            " auto-targets MD for those presets."
        ),
    ),
    "rf": DomainSpec(
        domain="rf",
        default_variant="arm_rf_summary",
        presets=RF_PRESETS,
        aliases=_RF_ALIASES,
        description=(
            "RF monitoring (``show ap arm …``, radio tables) plus RF configuration"
            " profiles (``show rf …``, Mobility Conductor)."
        ),
    ),
    "airmatch": DomainSpec(
        domain="airmatch",
        default_variant="optimization",
        presets=AIRMATCH_PRESETS,
        aliases=_AIRMATCH_ALIASES,
        description=(
            "AirMatch (``show airmatch …``): optimization jobs, solutions,"
            " profile, partition, and debug views on Mobility Conductor."
        ),
    ),
    "datapath": DomainSpec(
        domain="datapath",
        default_variant="tunnel",
        presets=DATAPATH_PRESETS,
        aliases=_DATAPATH_ALIASES,
        description=(
            "``show datapath *`` forwarding-plane diagnostics for traffic-related"
            " troubleshooting (``utilization`` for datapath CPU load; bridge / cluster /"
            " session / tunnel / user / vlan / …)."
        ),
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
