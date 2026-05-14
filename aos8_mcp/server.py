"""FastMCP entry point for the AOS8 read-only MCP server.

Tool surface (every domain tool follows the same shape: ``variant`` + optional
``cli_suffix`` / ``command_override`` / ``max_lines`` / ``max_rows`` / ``use_cache``):

* Session lifecycle:
    - aos8_session_create_from_config
    - aos8_session_create
    - aos8_session_destroy
    - aos8_session_status

* Free-form & discovery:
    - aos8_show           Run any read-only ``show ...`` directly.
    - aos8_catalog        Browse every domain + variant + description.

* Domain shortcuts (``show`` presets grouped by use case):
    - aos8_controllers, aos8_clients, aos8_aps, aos8_wlan, aos8_log,
      aos8_system, aos8_network, aos8_aaa, aos8_cluster, aos8_rf,
      aos8_datapath

* Composite diagnostics (chain several ``show`` calls):
    - aos8_ap_diagnose, aos8_client_diagnose, aos8_health_overview,
      aos8_forwarding_overview
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from aos8_mcp.aruba_client import ArubaHttpError
from aos8_mcp.devices_config import (
    default_devices_config_path,
    load_devices_config,
    resolve_md_logins,
)
from aos8_mcp.normalize import normalize_payload
from aos8_mcp.session_store import store
from aos8_mcp.show_registry import (
    CacheTier,
    NormalizerHint,
    ShowPreset,
    domain_catalog,
    full_catalog,
    get_domain,
    resolve_preset,
)
from aos8_mcp.truncate import apply_truncation


# ---------------------------------------------------------------------------
# Configuration (env-driven)
# ---------------------------------------------------------------------------
_HOST = os.environ.get("AOS8_MCP_HOST", "0.0.0.0")
_PORT = int(os.environ.get("AOS8_MCP_PORT", "8765"))

# Backwards compatible: AOS8_CACHE_TTL_SECONDS still drives the "near_realtime"
# tier default. Tiered overrides are also available via dedicated env vars.
_CACHE_DEFAULT_TTL = float(os.environ.get("AOS8_CACHE_TTL_SECONDS", "15"))
_CACHE_STATIC_TTL = float(os.environ.get("AOS8_CACHE_STATIC_TTL", "120"))
_CACHE_REALTIME_TTL = float(os.environ.get("AOS8_CACHE_REALTIME_TTL", "0"))

store.cache.configure_default_ttl(_CACHE_DEFAULT_TTL)
store.cache.configure_tier_ttl("static", _CACHE_STATIC_TTL)
store.cache.configure_tier_ttl("near_realtime", _CACHE_DEFAULT_TTL)
store.cache.configure_tier_ttl("realtime", _CACHE_REALTIME_TTL)

_DEFAULT_LOG_TAIL = int(os.environ.get("AOS8_LOG_DEFAULT_TAIL", "200"))
_DEFAULT_TABLE_CAP = int(os.environ.get("AOS8_TABLE_DEFAULT_CAP", "500"))

# Auto-reap idle sessions (in seconds). ``0`` disables the reaper (legacy behavior).
_IDLE_TIMEOUT = float(os.environ.get("AOS8_SESSION_IDLE_TIMEOUT_SECONDS", "1800"))
_IDLE_SCAN = float(os.environ.get("AOS8_SESSION_IDLE_SCAN_SECONDS", "60"))
store.configure_idle_reap(_IDLE_TIMEOUT, _IDLE_SCAN)

_STATELESS_HTTP = os.environ.get("AOS8_MCP_STATELESS_HTTP", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


# ---------------------------------------------------------------------------
# Input hygiene
# ---------------------------------------------------------------------------
_FORBIDDEN_COMMAND_CHARS = re.compile(r"[;`&]|\|\|")


def _coerce_optional_str(value: str | None) -> str | None:
    """Some browser MCP frontends serialize blank fields as literal ``"undefined"``."""
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.casefold() in ("undefined", "null", "none"):
        return None
    return s


def _validate_show_command(cmd: str) -> str | None:
    c = cmd.strip()
    if not c:
        return "Empty command."
    if "\n" in c or "\r" in c:
        return "Multi-line commands are not allowed."
    if _FORBIDDEN_COMMAND_CHARS.search(c):
        return "Disallowed character in command (`;`, `&`, ` `` `, or `||`)."
    if not c.lower().startswith("show "):
        return "Only 'show ' commands are allowed."
    return None


def _compose_command(base: str, cli_suffix: str | None) -> str:
    base = base.strip()
    if not cli_suffix:
        return base
    suf = cli_suffix.strip()
    if suf.startswith("|"):
        return f"{base} {suf}"
    return f"{base} | {suf}"


def _escape_for_include(token: str) -> str:
    """Aruba CLI ``| include`` accepts a regex; keep it simple by stripping pipes."""
    return token.replace("|", "").strip()


def _compose_datapath_command(
    base: str,
    *,
    ap_name: str | None,
    ip_addr: str | None,
    arg: str | None,
) -> str:
    """Append the typical ``ap-name <name>`` / ``ip-addr <ip>`` / positional arg.

    The keyword tokens are only added when the base command does not already
    contain them, so callers can either pick a preset such as ``bridge`` and
    pass ``ap_name`` (-> ``show datapath bridge ap-name X``) or a preset such
    as ``bridge_table`` and pass ``arg=<macaddr>`` (-> ``show datapath bridge
    table aa:bb:..``). ``arg`` is appended verbatim and is intended for
    positional values that the CLI does not gate behind a keyword.
    """
    cmd = base.strip()
    base_lower = cmd.lower()
    if ap_name and "ap-name" not in base_lower:
        cmd = f"{cmd} ap-name {ap_name.strip()}"
    if ip_addr and "ip-addr" not in base_lower:
        cmd = f"{cmd} ip-addr {ip_addr.strip()}"
    if arg:
        cmd = f"{cmd} {arg.strip()}"
    return cmd


# ---------------------------------------------------------------------------
# MCP application
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "aos8-mcp-server",
    instructions=(
        "Aruba AOS 8.x read-only MCP for MM+MD architectures.\n"
        "Workflow:\n"
        "  1) Create a session via aos8_session_create_from_config (preferred) or aos8_session_create.\n"
        "  2) Call domain tools with the returned session_id. Use aos8_catalog to discover\n"
        "     available presets across domains: controllers, clients, aps, wlan, log,\n"
        "     system, network, aaa, cluster, rf, datapath.\n"
        "  3) Use aos8_show for ad-hoc 'show ...' commands; use aos8_*_diagnose for\n"
        "     guided AP/client/system troubleshooting; use aos8_datapath /\n"
        "     aos8_forwarding_overview for forwarding-plane troubleshooting; use\n"
        "     aos8_cluster for cluster/HA views (auto-targets MD).\n"
        "  4) Tear down via aos8_session_destroy when finished.\n"
        "Notes:\n"
        "  - The session creation tool itself does not return device data; data tools\n"
        "    must run after a session exists.\n"
        "  - Output always contains 'raw' (original payload) and 'normalized' (heuristic\n"
        "    summary). Use max_lines / max_rows / cli_suffix='| include ...' to control size.\n"
        "  - MM-first execution with automatic fallback to MD on conductor-restricted commands.\n"
        "  - Cluster-specific note: 'show lc-cluster *' and 'show datapath cluster *'\n"
        "    only work on MDs; aos8_cluster picks the first configured MD by default\n"
        "    or honors an explicit md_ip parameter.\n"
        "  - Configure '#no paging' on controllers to avoid pagination artifacts.\n"
    ),
    host=_HOST,
    port=_PORT,
    streamable_http_path="/mcp",
    stateless_http=_STATELESS_HTTP,
)


# ---------------------------------------------------------------------------
# Core execution helpers
# ---------------------------------------------------------------------------
async def _with_normalize(
    result: dict[str, Any],
    hint: NormalizerHint,
) -> dict[str, Any]:
    out = dict(result)
    out["normalized"] = normalize_payload(hint, result.get("raw"))
    return out


async def _execute_preset(
    sid: str,
    preset: ShowPreset,
    *,
    cli_suffix: str | None,
    profile_name: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Resolve a preset's CLI, run it via the MM→MD fallback path, normalize, truncate."""
    base = preset.command
    if preset.needs_profile_name:
        pname = _coerce_optional_str(profile_name) or preset.profile_name_default
        if pname:
            base = f"{base} {pname.strip()}"
    cmd = _compose_command(base, cli_suffix)
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}
    try:
        raw = await store.show_with_mm_then_md_fallback(
            sid, cmd, use_cache=use_cache, cache_tier=preset.cache_tier
        )
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}
    enriched = await _with_normalize(raw, preset.normalizer)
    enriched = apply_truncation(enriched, max_lines=max_lines, max_rows=max_rows)
    enriched["variant"] = preset.key
    enriched["cache_tier"] = preset.cache_tier
    return {"ok": True, **enriched}


async def _run_domain(
    *,
    session_id: str,
    domain: str,
    variant: str | None,
    cli_suffix: str | None,
    command_override: str | None,
    profile_name: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
    default_max_lines: int | None = None,
    default_max_rows: int | None = None,
) -> dict[str, Any]:
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}
    suf = _coerce_optional_str(cli_suffix)
    override = _coerce_optional_str(command_override)
    profile = _coerce_optional_str(profile_name)
    v = _coerce_optional_str(variant)

    effective_max_lines = max_lines if max_lines is not None else default_max_lines
    effective_max_rows = max_rows if max_rows is not None else default_max_rows

    # command_override 走旁路：不查注册表，直接执行
    if override:
        cmd = _compose_command(override, suf)
        err = _validate_show_command(cmd)
        if err:
            return {"ok": False, "error": err}
        try:
            raw = await store.show_with_mm_then_md_fallback(
                sid, cmd, use_cache=use_cache, cache_tier="near_realtime"
            )
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        except ArubaHttpError as e:
            return {"ok": False, "error": str(e)}
        enriched = await _with_normalize(raw, "generic")
        enriched = apply_truncation(
            enriched, max_lines=effective_max_lines, max_rows=effective_max_rows
        )
        return {"ok": True, "domain": domain, **enriched}

    try:
        preset = resolve_preset(domain, v)
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    result = await _execute_preset(
        sid,
        preset,
        cli_suffix=suf,
        profile_name=profile,
        use_cache=use_cache,
        max_lines=effective_max_lines,
        max_rows=effective_max_rows,
    )
    if result.get("ok"):
        result["domain"] = domain
    return result


# ===========================================================================
# Session lifecycle
# ===========================================================================
@mcp.tool()
async def aos8_session_create_from_config(config_path: str = "") -> dict[str, Any]:
    """Create a session from a local YAML (recommended; no password in chat).

    Reads ``aos8.devices.yaml`` in the current working directory, the path
    pointed to by ``AOS8_DEVICES_CONFIG``, or ``config_path`` when provided.
    """
    path = Path(config_path.strip()).expanduser() if config_path.strip() else None
    try:
        cfg = load_devices_config(path)
        md_ips, md_logins = resolve_md_logins(cfg)
        sid, login_body = await store.create(
            mm_host=cfg.mm.ip,
            username=cfg.mm.username,
            password=cfg.mm.password,
            md_ips=md_ips,
            verify_ssl=cfg.verify_ssl,
            md_logins=md_logins,
        )
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except ValidationError as e:
        return {"ok": False, "error": f"Invalid config fields: {e}"}
    gr = login_body.get("_global_result") if isinstance(login_body, dict) else {}
    cfg_path_used = str(path.resolve()) if path else str(default_devices_config_path())
    return {
        "ok": True,
        "session_id": sid,
        "config_path": cfg_path_used,
        "mm_ip": cfg.mm.ip.strip(),
        "md_ips": md_ips,
        "login_status_str": gr.get("status_str") if isinstance(gr, dict) else None,
        "hint": "Credentials are kept in process memory only. Call aos8_session_destroy when done.",
    }


@mcp.tool()
async def aos8_session_create(
    mm_ip: str,
    username: str,
    password: str,
    md_ips: list[str] | None = None,
    verify_ssl: bool = False,
) -> dict[str, Any]:
    """Create a session by passing the MM credentials inline.

    Prefer ``aos8_session_create_from_config`` to avoid sending passwords through
    the chat transcript.

    ``verify_ssl=False`` skips TLS verification (equivalent to ``curl --insecure``),
    which is common in lab / private-CA scenarios.
    """
    try:
        sid, login_body = await store.create(
            mm_host=mm_ip,
            username=username,
            password=password,
            md_ips=md_ips,
            verify_ssl=verify_ssl,
            md_logins=None,
        )
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}
    gr = login_body.get("_global_result") if isinstance(login_body, dict) else {}
    return {
        "ok": True,
        "session_id": sid,
        "mm_ip": mm_ip.strip(),
        "md_ips": list(md_ips or []),
        "login_status_str": gr.get("status_str") if isinstance(gr, dict) else None,
        "hint": "Credentials are kept in process memory only. Call aos8_session_destroy when done.",
    }


@mcp.tool()
async def aos8_session_destroy(session_id: str) -> dict[str, Any]:
    """Log out the MM and any MD clients, then drop the cached responses."""
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}
    try:
        await store.destroy(sid)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "session_id": sid}


@mcp.tool()
async def aos8_session_status(session_id: str) -> dict[str, Any]:
    """Self-check: is the session alive? which MM/MD clients are still logged in?

    Useful when a previous tool call returns an auth error and you want to
    confirm whether the auto-relogin succeeded.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}
    try:
        info = await store.describe(sid)
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    cache_size = await store.cache.size()
    return {
        "ok": True,
        **info,
        "cache_size": cache_size,
        "idle_timeout_seconds": store.idle_timeout,
        "reap_interval_seconds": store.reap_interval,
    }


# ===========================================================================
# Free-form & discovery
# ===========================================================================
@mcp.tool()
async def aos8_show(
    session_id: str,
    command: str,
    target: Literal["mm", "md"] = "mm",
    md_ip: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Run an arbitrary read-only ``show`` command.

    ``target='mm'`` (default) uses the MM, falling back to configured MDs when
    the controller reports the command is not applicable on conductor.

    ``max_lines`` / ``max_rows`` trim the response server-side for log-style
    and table-style outputs, respectively.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}
    cmd = (_coerce_optional_str(command) or "").strip()
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}
    md_eff = _coerce_optional_str(md_ip)
    try:
        raw = await store.show_on_target(
            sid,
            cmd,
            target=target,
            md_ip=md_eff,
            use_cache=use_cache,
            cache_tier="near_realtime",
        )
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except (ArubaHttpError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    enriched = await _with_normalize(raw, "generic")
    enriched = apply_truncation(enriched, max_lines=max_lines, max_rows=max_rows)
    return {"ok": True, **enriched}


@mcp.tool()
async def aos8_catalog(domain: str | None = None) -> dict[str, Any]:
    """Discover every domain + variant + default command.

    Pass ``domain`` to filter to a single bucket (e.g. ``"aps"``). Without it,
    the full ``{domain: {meta, variants}}`` map is returned.
    """
    name = _coerce_optional_str(domain)
    if name:
        try:
            spec = get_domain(name)
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "domain": name,
            "default_variant": spec.default_variant,
            "description": spec.description,
            "variants": domain_catalog(name),
        }
    return {"ok": True, "catalog": full_catalog()}


# ===========================================================================
# Domain shortcuts
# ===========================================================================
@mcp.tool()
async def aos8_controllers(
    session_id: str,
    variant: str = "switches",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Controller hierarchy views (default: ``show switches``).

    Use ``aos8_catalog(domain='controllers')`` to list other variants.
    """
    return await _run_domain(
        session_id=session_id,
        domain="controllers",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_rows=max_rows,
        default_max_rows=_DEFAULT_TABLE_CAP,
    )


@mcp.tool()
async def aos8_clients(
    session_id: str,
    variant: str = "global_user_table_list",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Wireless user views (default: ``show global-user-table list``).

    To find users on a given AP, pass ``cli_suffix='| include AP-name'``.
    """
    return await _run_domain(
        session_id=session_id,
        domain="clients",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_rows=max_rows,
        default_max_rows=_DEFAULT_TABLE_CAP,
    )


@mcp.tool()
async def aos8_aps(
    session_id: str,
    variant: str = "database",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """``show ap *`` subcommands (default: ``show ap database``).

    Use ``aos8_catalog(domain='aps')`` to list available variants.
    """
    return await _run_domain(
        session_id=session_id,
        domain="aps",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_rows=max_rows,
        default_max_rows=_DEFAULT_TABLE_CAP,
    )


@mcp.tool()
async def aos8_wlan(
    session_id: str,
    variant: str = "virtual_ap",
    profile_name: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """``show wlan *`` subcommands (default: ``show wlan virtual-ap``).

    For SSID profile variants pass ``profile_name`` (defaults to ``default``
    when omitted for ``ssid_profile`` / ``he_ssid_profile`` / ``ht_ssid_profile``).
    """
    return await _run_domain(
        session_id=session_id,
        domain="wlan",
        variant=variant,
        profile_name=profile_name,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_rows=max_rows,
        default_max_rows=_DEFAULT_TABLE_CAP,
    )


@mcp.tool()
async def aos8_log(
    session_id: str,
    variant: str = "all",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = False,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """Controller log views (default: ``show log all``).

    To keep the response manageable, the server returns the last
    ``AOS8_LOG_DEFAULT_TAIL`` (default 200) lines unless ``max_lines`` overrides it.
    Combine with ``cli_suffix='| include <keyword>'`` for targeted searches.
    """
    return await _run_domain(
        session_id=session_id,
        domain="log",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_lines=max_lines,
        default_max_lines=_DEFAULT_LOG_TAIL,
    )


@mcp.tool()
async def aos8_system(
    session_id: str,
    variant: str = "version",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Platform health & identification (version, license, cpuload, memory, storage, ...)."""
    return await _run_domain(
        session_id=session_id,
        domain="system",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
    )


@mcp.tool()
async def aos8_network(
    session_id: str,
    variant: str = "ip_interface_brief",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """L2/L3 views (VLAN, ports, IP interfaces, routing, ARP, DHCP).

    Default is ``show ip interface brief``. Use ``aos8_catalog(domain='network')``
    to list other variants.
    """
    return await _run_domain(
        session_id=session_id,
        domain="network",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_rows=max_rows,
        default_max_rows=_DEFAULT_TABLE_CAP,
    )


@mcp.tool()
async def aos8_aaa(
    session_id: str,
    variant: str = "state_messages",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """AAA views: server status, server-groups, profiles, recent state messages.

    Default ``state_messages`` is useful for chasing recent auth failures
    (combine with ``cli_suffix='| include <user_or_mac>'``).
    """
    return await _run_domain(
        session_id=session_id,
        domain="aaa",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_lines=max_lines,
        max_rows=max_rows,
        default_max_lines=_DEFAULT_LOG_TAIL,
        default_max_rows=_DEFAULT_TABLE_CAP,
    )


def _cluster_command_prefers_md(command: str) -> bool:
    """Return True for commands documented as MD-only (``Config/enable mode in the managed device``)."""
    c = command.strip().lower()
    return c.startswith("show lc-cluster") or c.startswith("show datapath cluster")


@mcp.tool()
async def aos8_cluster(
    session_id: str,
    variant: str = "lc_cluster_group_membership",
    md_ip: str | None = None,
    arg: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Cluster / HA / master-redundancy views — auto-targets MD for ``lc-cluster`` and ``datapath cluster``.

    Cluster diagnostics live on the managed device: every ``show lc-cluster *``
    and ``show datapath cluster *`` command is documented as runnable in
    enable/config mode on the MD only, so calling them on the conductor (MM)
    just returns ``This command is not applicable on conductor``. This tool
    therefore dispatches MD-only presets directly to an MD (no wasted MM
    round-trip), while keeping standard MM-then-MD fallback for cross-domain
    helpers like ``switches_state`` / ``heartbeat`` / ``master_redundancy``.

    MD selection:
      * ``md_ip``  — explicit member IP. Logs in on demand using MM credentials
        if no per-MD credentials exist in the session.
      * Otherwise the first MD configured in the session is used (typical
        cluster setups expose identical state on every member, so this is
        usually fine).
      * If no MDs are configured at all, the MM-then-MD fallback path is used
        and a ``note`` field in the result explains why.

    Common variants (call ``aos8_catalog(domain='cluster')`` for the full list):
      * ``lc_cluster_group_membership`` (default)        — leader/member roster
      * ``lc_cluster_group_profile`` [arg=<profile>]     — profile detail
      * ``lc_cluster_heartbeat_counters``                — per-peer heartbeat
      * ``lc_cluster_load_distribution_ap`` / ``..._client`` — AP/client distribution
      * ``lc_cluster_history`` / ``lc_cluster_global_events`` — connect/disconnect events
      * ``lc_cluster_vlan_probe_status``                 — L2 probing health
      * ``lc_cluster_papi_counters`` / ``lc_cluster_gsm_counters`` — control-plane health
      * ``lc_cluster_bucket_distribution_essid`` arg=<essid>
      * ``datapath_cluster`` / ``datapath_cluster_details`` [arg='peer <ip>']
      * ``datapath_cluster_heartbeat_counters``

    The ``arg`` parameter is appended verbatim to the base command — useful for
    ``group-profile <name>``, ``details peer <ip>``, ``bucket distribution
    essid <name>``, etc. Combine with ``cli_suffix='| include ...'`` for
    further filtering.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}

    suf = _coerce_optional_str(cli_suffix)
    override = _coerce_optional_str(command_override)
    extra = _coerce_optional_str(arg)
    explicit_md = _coerce_optional_str(md_ip)
    v = _coerce_optional_str(variant)

    effective_max_lines = max_lines
    effective_max_rows = max_rows if max_rows is not None else _DEFAULT_TABLE_CAP

    try:
        sess = await store.get(sid)
    except KeyError as e:
        return {"ok": False, "error": str(e)}

    if override:
        base_cmd = override
        cache_tier: CacheTier = "near_realtime"
        normalizer: NormalizerHint = "generic"
        variant_used: str | None = None
    else:
        try:
            preset = resolve_preset("cluster", v)
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        base_cmd = preset.command
        cache_tier = preset.cache_tier
        normalizer = preset.normalizer
        variant_used = preset.key

    if extra:
        base_cmd = f"{base_cmd} {extra}"
    cmd = _compose_command(base_cmd, suf)
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}

    md_only = _cluster_command_prefers_md(cmd)
    chosen_md = explicit_md or (sess.md_ips[0] if sess.md_ips else None)
    target_note: str | None = None

    try:
        if md_only and chosen_md:
            raw = await store.show_on_target(
                sid,
                cmd,
                target="md",
                md_ip=chosen_md,
                use_cache=use_cache,
                cache_tier=cache_tier,
            )
        else:
            if md_only and not chosen_md:
                target_note = (
                    "MD-only command but no MDs are configured for this session. "
                    "Falling back to MM (which will report 'not applicable on conductor'). "
                    "Configure md_ips via aos8.devices.yaml or pass md_ip explicitly."
                )
            raw = await store.show_with_mm_then_md_fallback(
                sid, cmd, use_cache=use_cache, cache_tier=cache_tier
            )
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except (ArubaHttpError, ValueError) as e:
        return {"ok": False, "error": str(e)}

    enriched = await _with_normalize(raw, normalizer)
    enriched = apply_truncation(
        enriched, max_lines=effective_max_lines, max_rows=effective_max_rows
    )
    enriched["domain"] = "cluster"
    if variant_used:
        enriched["variant"] = variant_used
        enriched["cache_tier"] = cache_tier
    if target_note:
        existing = enriched.get("note")
        enriched["note"] = (
            f"{existing}\n{target_note}" if existing else target_note
        )
    return {"ok": True, **enriched}


@mcp.tool()
async def aos8_rf(
    session_id: str,
    variant: str = "arm_rf_summary",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Curated RF monitoring views (ARM RF summary, monitor stats, BSS table, radio summary)."""
    return await _run_domain(
        session_id=session_id,
        domain="rf",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_rows=max_rows,
        default_max_rows=_DEFAULT_TABLE_CAP,
    )


@mcp.tool()
async def aos8_datapath(
    session_id: str,
    variant: str = "tunnel",
    ap_name: str | None = None,
    ip_addr: str | None = None,
    arg: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = False,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Forwarding-plane diagnostics — ``show datapath *`` subcommand family.

    Use this when troubleshooting traffic-related issues (clients can associate
    but cannot pass traffic, intermittent forwarding, tunnel/IPsec problems,
    cluster heartbeat anomalies, etc.).

    Common variants (call ``aos8_catalog(domain='datapath')`` for the full list):
      * ``tunnel`` / ``tunnel_counters`` / ``tunnel_id``  — AP GRE & IPsec tunnels
      * ``bridge`` / ``bridge_counters`` / ``bridge_table`` — L2 bridge state
      * ``session`` / ``session_counters`` / ``session_table`` — datapath sessions
      * ``user`` / ``user_table`` / ``user_counters``     — datapath user table
      * ``vlan`` / ``vlan_table`` / ``vlan_pvst``         — VLAN membership
      * ``frame`` / ``frame_counters``                    — packet processing counters
      * ``crypto_counters`` / ``cluster_heartbeat_counters`` — IPsec / HA health
      * ``mobility_*``                                    — L3 mobility tables
      * ``route`` / ``route_cache`` / ``acl`` / ``ipsec_map``

    Typed parameters:
      * ``ap_name``  — appended as ``ap-name <name>`` when the variant supports it.
      * ``ip_addr``  — appended as ``ip-addr <ip>`` when the variant supports it.
      * ``arg``      — appended verbatim, used for positional values such as the
                       MAC after ``bridge table``, the IP after ``session table``,
                       the tunnel id after ``tunnel_id``, the session id after
                       ``session_session_id``, or qualifiers like ``trusted-vlan``.

    Pass ``cli_suffix='| include <token>'`` for further filtering, ``max_rows`` /
    ``max_lines`` to cap large outputs. ``use_cache`` defaults to False because
    every datapath preset is in the realtime tier.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}

    suf = _coerce_optional_str(cli_suffix)
    override = _coerce_optional_str(command_override)
    apn = _coerce_optional_str(ap_name)
    ipa = _coerce_optional_str(ip_addr)
    extra = _coerce_optional_str(arg)
    v = _coerce_optional_str(variant)

    effective_max_lines = max_lines
    effective_max_rows = max_rows if max_rows is not None else _DEFAULT_TABLE_CAP

    if override:
        composed = _compose_datapath_command(
            override, ap_name=apn, ip_addr=ipa, arg=extra
        )
        cmd = _compose_command(composed, suf)
        err = _validate_show_command(cmd)
        if err:
            return {"ok": False, "error": err}
        try:
            raw = await store.show_with_mm_then_md_fallback(
                sid, cmd, use_cache=use_cache, cache_tier="realtime"
            )
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        except ArubaHttpError as e:
            return {"ok": False, "error": str(e)}
        enriched = await _with_normalize(raw, "generic")
        enriched = apply_truncation(
            enriched, max_lines=effective_max_lines, max_rows=effective_max_rows
        )
        return {"ok": True, "domain": "datapath", **enriched}

    try:
        preset = resolve_preset("datapath", v)
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    base_cmd = _compose_datapath_command(
        preset.command, ap_name=apn, ip_addr=ipa, arg=extra
    )
    cmd = _compose_command(base_cmd, suf)
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}

    try:
        raw = await store.show_with_mm_then_md_fallback(
            sid, cmd, use_cache=use_cache, cache_tier=preset.cache_tier
        )
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}

    enriched = await _with_normalize(raw, preset.normalizer)
    enriched = apply_truncation(
        enriched, max_lines=effective_max_lines, max_rows=effective_max_rows
    )
    enriched["variant"] = preset.key
    enriched["cache_tier"] = preset.cache_tier
    enriched["domain"] = "datapath"
    return {"ok": True, **enriched}


# ===========================================================================
# Composite diagnostics
# ===========================================================================
async def _gather_steps(
    sid: str, steps: list[tuple[str, ShowPreset, str | None]]
) -> list[dict[str, Any]]:
    """Run several presets in parallel; return one summary dict per step."""
    coros = [
        _execute_preset(
            sid,
            preset,
            cli_suffix=suffix,
            use_cache=True,
            max_lines=_DEFAULT_LOG_TAIL,
            max_rows=_DEFAULT_TABLE_CAP,
        )
        for _, preset, suffix in steps
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: list[dict[str, Any]] = []
    for (label, preset, suffix), res in zip(steps, results, strict=False):
        if isinstance(res, Exception):
            out.append(
                {
                    "step": label,
                    "command": preset.command,
                    "ok": False,
                    "error": str(res),
                }
            )
            continue
        out.append(
            {
                "step": label,
                "command": res.get("command") or preset.command,
                "applied_suffix": suffix,
                **res,
            }
        )
    return out


@mcp.tool()
async def aos8_ap_diagnose(
    session_id: str,
    ap_name: str,
    include_log_tail: bool = True,
) -> dict[str, Any]:
    """Run several ``show ap *`` queries for a single AP and aggregate the highlights.

    Steps executed in parallel:
      * ``show ap database`` (filtered)         — registration / status / flags
      * ``show ap active`` (filtered)           — currently active radios
      * ``show ap radio-summary`` (filtered)    — per-radio channel / power
      * ``show ap bss-table`` (filtered)        — BSSIDs and load
      * ``show global-user-table list`` (filtered) — associated users
      * (optional) recent ``show log all`` lines mentioning the AP
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}
    name = _coerce_optional_str(ap_name)
    if not name:
        return {"ok": False, "error": "ap_name is required."}
    token = _escape_for_include(name)
    inc = f"| include {token}"

    steps: list[tuple[str, ShowPreset, str | None]] = [
        ("database", resolve_preset("aps", "database"), inc),
        ("active", resolve_preset("aps", "active"), inc),
        ("radio_summary", resolve_preset("aps", "radio_summary"), inc),
        ("bss_table", resolve_preset("aps", "bss_table"), inc),
        ("clients_on_ap", resolve_preset("clients", "global_user_table_list"), inc),
    ]
    if include_log_tail:
        steps.append(("recent_log", resolve_preset("log", "all"), inc))

    results = await _gather_steps(sid, steps)
    summary = _summarize_ap_diagnose(name, results)
    return {"ok": True, "ap_name": name, "summary": summary, "steps": results}


def _summarize_ap_diagnose(ap_name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"ap_name": ap_name}
    for s in steps:
        label = s.get("step")
        if not s.get("ok"):
            out[label] = {"error": s.get("error", "failed")}
            continue
        norm = s.get("normalized") or {}
        count = norm.get("count")
        if count is not None:
            out[label] = {"matched_rows": count}
        elif norm.get("kind") == "log":
            out[label] = {"log_lines": norm.get("line_count_total") or norm.get("line_count")}
        else:
            out[label] = {"kind": norm.get("kind") or "unknown"}
    return out


@mcp.tool()
async def aos8_client_diagnose(
    session_id: str,
    identifier: str,
    include_log_tail: bool = True,
) -> dict[str, Any]:
    """Trace a wireless client by MAC, IP, or username.

    Steps executed in parallel (all filtered by the identifier):
      * ``show global-user-table list``         — overall presence
      * ``show user-table``                     — local-controller user view
      * ``show ap association``                 — which AP / radio they sit on
      * ``show aaa state messages``             — recent AAA activity
      * (optional) recent ``show log all`` lines mentioning the identifier
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}
    ident = _coerce_optional_str(identifier)
    if not ident:
        return {"ok": False, "error": "identifier is required (mac / ip / username)."}
    token = _escape_for_include(ident)
    inc = f"| include {token}"

    steps: list[tuple[str, ShowPreset, str | None]] = [
        ("global_user_table", resolve_preset("clients", "global_user_table_list"), inc),
        ("user_table", resolve_preset("clients", "user_table"), inc),
        ("ap_association", resolve_preset("aps", "association"), inc),
        ("aaa_state_messages", resolve_preset("aaa", "state_messages"), inc),
    ]
    if include_log_tail:
        steps.append(("recent_log", resolve_preset("log", "all"), inc))

    results = await _gather_steps(sid, steps)
    return {
        "ok": True,
        "identifier": ident,
        "steps": results,
    }


@mcp.tool()
async def aos8_forwarding_overview(
    session_id: str,
    ap_name: str | None = None,
) -> dict[str, Any]:
    """One-shot forwarding-plane health snapshot via parallel ``show datapath`` calls.

    Steps executed in parallel:
      * ``show datapath cluster``                  — controller HA forwarding view
      * ``show datapath cluster heartbeat counters`` — HA heartbeat health
      * ``show datapath tunnel counters``          — GRE / IPsec tunnel state
      * ``show datapath frame counters``           — packet processing counters
      * ``show datapath session counters``         — session table capacity
      * ``show datapath bridge counters``          — L2 bridge table capacity
      * ``show datapath user counters``            — datapath user table capacity
      * ``show datapath crypto counters``          — IPsec / dot1x term health
      * (optional, when ``ap_name`` is set) ``show datapath tunnel | include <ap>``

    Use this as the morning check / opening triage step for any forwarding
    incident before drilling into a specific subsystem with ``aos8_datapath``.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}

    steps: list[tuple[str, ShowPreset, str | None]] = [
        ("cluster", resolve_preset("datapath", "cluster"), None),
        ("cluster_heartbeat_counters", resolve_preset("datapath", "cluster_heartbeat_counters"), None),
        ("tunnel_counters", resolve_preset("datapath", "tunnel_counters"), None),
        ("frame_counters", resolve_preset("datapath", "frame_counters"), None),
        ("session_counters", resolve_preset("datapath", "session_counters"), None),
        ("bridge_counters", resolve_preset("datapath", "bridge_counters"), None),
        ("user_counters", resolve_preset("datapath", "user_counters"), None),
        ("crypto_counters", resolve_preset("datapath", "crypto_counters"), None),
    ]

    apn = _coerce_optional_str(ap_name)
    if apn:
        token = _escape_for_include(apn)
        steps.append(("tunnels_for_ap", resolve_preset("datapath", "tunnel"), f"| include {token}"))

    results = await _gather_steps(sid, steps)
    summary: dict[str, Any] = {}
    for s in results:
        label = s["step"]
        if not s.get("ok"):
            summary[label] = {"error": s.get("error", "failed")}
            continue
        norm = s.get("normalized") or {}
        if norm.get("kind") == "log":
            summary[label] = {"log_lines": norm.get("line_count_total") or norm.get("line_count")}
        elif "count" in norm:
            summary[label] = {
                "count": norm.get("count_total") or norm.get("count"),
            }
        else:
            summary[label] = {"kind": norm.get("kind") or "unknown"}
    return {"ok": True, "ap_name": apn, "summary": summary, "steps": results}


@mcp.tool()
async def aos8_health_overview(session_id: str) -> dict[str, Any]:
    """One-shot platform overview (version, licenses, controllers, cluster, APs, clients).

    Useful as a 'morning check' or initial triage step before drilling into a
    specific problem.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}

    steps: list[tuple[str, ShowPreset, str | None]] = [
        ("version", resolve_preset("system", "version"), None),
        ("license", resolve_preset("system", "license"), None),
        ("switches", resolve_preset("controllers", "switches"), None),
        ("cluster", resolve_preset("cluster", "lc_cluster_group_membership"), None),
        ("ap_database_summary", resolve_preset("aps", "database_summary"), None),
        ("ap_database", resolve_preset("aps", "database"), None),
        ("clients_count", resolve_preset("clients", "global_user_table_list"), None),
    ]
    results = await _gather_steps(sid, steps)

    summary: dict[str, Any] = {}
    for s in results:
        label = s["step"]
        if not s.get("ok"):
            summary[label] = {"error": s.get("error", "failed")}
            continue
        norm = s.get("normalized") or {}
        if norm.get("kind") in {
            "access_points",
            "active_aps",
            "users",
            "switches",
            "members",
            "licenses",
        }:
            summary[label] = {
                "count": norm.get("count_total") or norm.get("count"),
            }
        else:
            summary[label] = {"kind": norm.get("kind") or "unknown"}
    return {"ok": True, "summary": summary, "steps": results}


# ===========================================================================
# Entry point
# ===========================================================================
def run() -> None:
    """Serve over Streamable HTTP with permissive CORS for browser MCP clients."""
    import anyio
    import uvicorn
    from starlette.middleware.cors import CORSMiddleware

    inner = mcp.streamable_http_app()
    app = CORSMiddleware(
        inner,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
        expose_headers=["mcp-session-id", "mcp-protocol-version"],
    )

    async def _serve() -> None:
        config = uvicorn.Config(
            app,
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=mcp.settings.log_level.lower(),
        )
        await uvicorn.Server(config).serve()

    anyio.run(_serve)
