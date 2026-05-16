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
      aos8_airmatch, aos8_datapath

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

from aos8_mcp.aruba_client import ArubaHttpError, configured_uidaruba_ttl_seconds
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


_AIRMATCH_AP_NAME_VARIANTS = frozenset(
    {"solution", "debug_apinfo", "debug_history", "debug_client_history"}
)

_AAA_OPTIONAL_PROFILE_PRESETS = frozenset(
    {"authentication_dot1x", "authentication_mac", "authentication_captive_portal"}
)


def _compose_aaa_extra_cli(
    preset_key: str,
    *,
    profile_name: str | None,
    arg: str | None,
) -> str | None:
    """Optional profile suffix plus verbatim ``arg`` for AAA ``show`` presets."""
    parts: list[str] = []
    pname = _coerce_optional_str(profile_name)
    if pname and preset_key in _AAA_OPTIONAL_PROFILE_PRESETS:
        parts.append(pname.strip())
    suf = _coerce_optional_str(arg)
    if suf:
        parts.append(suf.strip())
    return " ".join(parts) if parts else None


def _compose_airmatch_command(
    preset_key: str,
    base: str,
    *,
    ap_name: str | None,
    arg: str | None,
) -> str:
    """Append ``ap-name`` / extra tokens for ``show airmatch …`` presets."""
    cmd = base.strip()
    apn = _coerce_optional_str(ap_name)
    suf = _coerce_optional_str(arg)
    if apn and preset_key in _AIRMATCH_AP_NAME_VARIANTS:
        cmd = f"{cmd} ap-name {apn.strip()}"
    if suf:
        cmd = f"{cmd} {suf.strip()}"
    return cmd


# ---------------------------------------------------------------------------
# MCP application
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "aos8-mcp-server",
    instructions=(
        "Aruba AOS 8.x read-only MCP for MM+MD architectures.\n"
        "\n"
        "Workflow:\n"
        "  1) Create a session: aos8_session_create_from_config (preferred) or aos8_session_create.\n"
        "     This logs into the MM and every configured MD once (UIDARUBA ~15m TTL) so tokens exist\n"
        "     before data tools; each uncached show then re-uses stored credentials and, by default,\n"
        "     logs out after the HTTP request to avoid exhausting concurrent API sessions on devices.\n"
        "  2) Pass session_id into every data tool. Session creation returns no device show output.\n"
        "  3) If unsure which variant= preset key to use, call aos8_catalog (domain=... optional)\n"
        "     first; domain tools resolve variant -> 'show ...' from an internal preset registry.\n"
        "  4) For a single read-only CLI string not covered by presets, use aos8_show, or pass\n"
        "     command_override on a domain tool (must start with 'show ').\n"
        "  5) Tear down via aos8_session_destroy when finished.\n"
        "\n"
        "Tool selection (map user intent -> tool; pick ONE primary path, then narrow):\n"
        "  - Controller / switch hierarchy: aos8_controllers\n"
        "  - Wireless clients (``show user`` / ``show user-table``, MD-first): aos8_clients\n"
        "  - AP inventory / radios / BSS: aos8_aps; one AP multi-step bundle: aos8_ap_diagnose(ap_name)\n"
        "  - WLAN / SSID / VAP profiles (``show wlan``, MD-first): aos8_wlan\n"
        "  - Controller logs: aos8_log (use max_lines for tails)\n"
        "  - License / platform / switchinfo: aos8_system\n"
        "  - VLAN / ports / routing / ARP / DHCP bindings: aos8_network\n"
        "  - AAA / RADIUS / dot1x / captive portal / state messages (MD-first): aos8_aaa\n"
        "    (profile_name and arg apply only to documented variants on that tool)\n"
        "  - LC-cluster + datapath cluster HA views: aos8_cluster (MD-only presets auto-target MD)\n"
        "  - RF monitoring + ``show rf`` profiles (MD-first): aos8_rf (arg appends profile names / trailing tokens)\n"
        "  - AirMatch jobs / solutions / debug on MM: aos8_airmatch\n"
        "  - Datapath forwarding (sessions, tunnels, users, vlan, utilization/cpu for datapath CPU):\n"
        "    aos8_datapath; multi-step forwarding snapshot: aos8_forwarding_overview\n"
        "  - Quick controller health bundle: aos8_health_overview(session_id)\n"
        "  - Guided client troubleshooting: aos8_client_diagnose\n"
        "\n"
        "Notes:\n"
        "  - Every successful data response includes 'raw' and 'normalized'. Prefer normalized\n"
        "    for counts/summaries; drill into raw when needed. Use max_lines / max_rows /\n"
        "    cli_suffix='| include ...' to cap huge tables.\n"
        "  - Execution is MM-first with automatic MD fallback when the MM rejects a command.\n"
        "  - aos8_cluster: 'show lc-cluster *' and 'show datapath cluster *' run on MDs; use md_ip\n"
        "    or the default first configured MD.\n"
        "  - Configure '#no paging' on controllers to reduce pagination artifacts.\n"
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


def _clients_command_prefers_md(command: str) -> bool:
    """True for CLI-Bank user-plane ``show`` commands that should hit an MD first.

    See ``sh-user.htm`` / ``sh-user-tab.htm``: ``show user``, ``show user-table``,
    ``show user-summary``, and ``show datapath user …`` forwarding views.
    ``show global-user-table`` stays on the conductor-first path (hierarchy roster).
    """
    c = command.strip().lower()
    if c.startswith("show global-user-table"):
        return False
    if c.startswith("show user-table"):
        return True
    if c.startswith("show user-summary"):
        return True
    if c == "show user" or c.startswith("show user "):
        return True
    if c.startswith("show datapath user"):
        return True
    return False


def _wlan_command_prefers_md(command: str) -> bool:
    """True for the entire ``show wlan`` family (CLI-Bank ``sh-wlan.htm``)."""
    c = command.strip().lower()
    return c == "show wlan" or c.startswith("show wlan ")


def _should_apply_md_first_bias(cmd: str, md_bias_domain: str | None) -> bool:
    """MD-first when command matches global rules or the tool domain (aaa / rf)."""
    if _clients_command_prefers_md(cmd) or _wlan_command_prefers_md(cmd):
        return True
    c = cmd.strip().lower()
    if md_bias_domain == "aaa":
        return c == "show aaa" or c.startswith("show aaa ")
    if md_bias_domain == "rf":
        return (
            c == "show ap"
            or c.startswith("show ap ")
            or c == "show rf"
            or c.startswith("show rf ")
        )
    return False


async def _fetch_show_with_md_first_bias(
    sid: str,
    cmd: str,
    *,
    use_cache: bool,
    cache_tier: CacheTier | None,
    md_ip: str | None = None,
    md_bias_domain: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """MM→MD fallback, except selected commands go straight to a configured MD when possible."""
    if not _should_apply_md_first_bias(cmd, md_bias_domain):
        raw = await store.show_with_mm_then_md_fallback(
            sid, cmd, use_cache=use_cache, cache_tier=cache_tier
        )
        return raw, None

    try:
        sess = await store.get(sid)
    except KeyError:
        raise
    chosen = _coerce_optional_str(md_ip) or (sess.md_ips[0] if sess.md_ips else None)
    if chosen:
        raw = await store.show_on_target(
            sid,
            cmd,
            target="md",
            md_ip=chosen,
            use_cache=use_cache,
            cache_tier=cache_tier,
        )
        return raw, None

    note = (
        "MD-first command but no MD is configured for this session; "
        "using MM then automatic MD fallback. Configure md_ips on the session "
        "(e.g. aos8.devices.yaml) or pass md_ip on aos8_clients / aos8_wlan / "
        "aos8_aaa / aos8_rf."
    )
    raw = await store.show_with_mm_then_md_fallback(
        sid, cmd, use_cache=use_cache, cache_tier=cache_tier
    )
    return raw, note


async def _execute_preset(
    sid: str,
    preset: ShowPreset,
    *,
    cli_suffix: str | None,
    profile_name: str | None = None,
    extra_cli: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
    md_ip: str | None = None,
    md_bias_domain: str | None = None,
) -> dict[str, Any]:
    """Resolve a preset's CLI, run it (MM→MD fallback, with MD-first bias where applicable), normalize."""
    base = preset.command
    if preset.needs_profile_name:
        pname = _coerce_optional_str(profile_name) or preset.profile_name_default
        if pname:
            base = f"{base} {pname.strip()}"
    extra = _coerce_optional_str(extra_cli)
    if extra:
        base = f"{base} {extra}"
    cmd = _compose_command(base, cli_suffix)
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}
    try:
        raw, bias_note = await _fetch_show_with_md_first_bias(
            sid,
            cmd,
            use_cache=use_cache,
            cache_tier=preset.cache_tier,
            md_ip=md_ip,
            md_bias_domain=md_bias_domain,
        )
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}
    enriched = await _with_normalize(raw, preset.normalizer)
    if bias_note:
        prev = enriched.get("note")
        enriched["note"] = f"{prev}\n{bias_note}" if prev else bias_note
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
    extra_cli: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
    default_max_lines: int | None = None,
    default_max_rows: int | None = None,
    md_ip: str | None = None,
) -> dict[str, Any]:
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}
    suf = _coerce_optional_str(cli_suffix)
    override = _coerce_optional_str(command_override)
    profile = _coerce_optional_str(profile_name)
    extra_tokens = _coerce_optional_str(extra_cli)
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
            raw, bias_note = await _fetch_show_with_md_first_bias(
                sid,
                cmd,
                use_cache=use_cache,
                cache_tier="near_realtime",
                md_ip=_coerce_optional_str(md_ip)
                if domain in ("clients", "wlan", "aaa", "rf")
                else None,
                md_bias_domain=domain,
            )
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        except ArubaHttpError as e:
            return {"ok": False, "error": str(e)}
        enriched = await _with_normalize(raw, "generic")
        if bias_note:
            prev = enriched.get("note")
            enriched["note"] = f"{prev}\n{bias_note}" if prev else bias_note
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
        extra_cli=extra_tokens,
        use_cache=use_cache,
        max_lines=effective_max_lines,
        max_rows=effective_max_rows,
        md_ip=_coerce_optional_str(md_ip)
        if domain in ("clients", "wlan", "aaa", "rf")
        else None,
        md_bias_domain=domain,
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
        "uidaruba_ttl_seconds": int(configured_uidaruba_ttl_seconds()),
        "logout_after_each_tool": store.logout_after_each_tool,
        "eager_login_device_count": 1 + len(md_ips),
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
        "uidaruba_ttl_seconds": int(configured_uidaruba_ttl_seconds()),
        "logout_after_each_tool": store.logout_after_each_tool,
        "eager_login_device_count": 1 + len(list(md_ips or [])),
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
    """Self-check: is the session alive? which MM/MD clients still hold active UIDARUBA tokens?

    Useful when a previous tool call returns an auth error and you want to
    confirm whether the auto-relogin succeeded.

    Note: when ``AOS8_LOGOUT_AFTER_EACH_TOOL`` is enabled (default), most tools
    end with an API logout, so ``mm_logged_in`` / MD ``logged_in`` are often
    false even though credentials remain in memory until ``aos8_session_destroy``.
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
    """Controller hierarchy views — the MM-side ``show switches`` family.

    Hierarchy roster:
      * ``switches`` (default)        — every controller registered
      * ``switches_all``              — explicit ``show switches all``
      * ``switches_summary``          — short status summary
      * ``switches_debug``            — extra debug info (MAC, node-path,
                                        uptime, crash-info, license, release type)
      * ``switches_regulatory``       — active regulatory file per controller

    Config-update state filters (helpful when chasing config-sync issues):
      * ``switches_state_down`` / ``state_complete`` / ``state_incomplete``
        / ``state_inprogress`` / ``state_required``

    Local-controller info (the box the session is logged into):
      * ``switch_software`` — software / model / build / uptime / reboot cause
      * ``switch_ip``       — management IP details

    Short aliases are accepted for ergonomics: ``all`` / ``debug`` /
    ``regulatory`` / ``summary`` / ``state_down`` / ``state_complete`` / etc.
    For a comprehensive *single-box* identity dump, use
    ``aos8_system(..., variant='switchinfo')``.
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
    variant: str = "user_table",
    md_ip: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Wireless user views — CLI-Bank ``show user`` / ``show user-table`` (MD-first).

    Official references:
      * [show user](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-user.htm)
      * [show user-table](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-user-tab.htm)

    Default preset is ``user_table`` (``show user-table``): full per-client context on
    the **managed device**. When ``md_ips`` are configured on the session, these
    commands are sent to the first MD immediately (no wasted MM round-trip); pass
    ``md_ip`` to pick a specific member.

    Conductor-wide roster (all MDs) remains available as ``variant='global_user_table_list'``
    (``show global-user-table list``) — that variant keeps the MM-first path.

    Filter examples (append via ``cli_suffix`` with a leading space, not ``|`` unless
    you intend a pipe filter): ``ap-name <name>``, ``role <role>``, ``mac <addr>``,
    ``ip <addr>``, ``essid \"My SSID\"``. For AP-name grep-style narrowing you can
    still use ``cli_suffix='| include <token>'``.
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
        md_ip=md_ip,
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
    md_ip: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """WLAN profile views — official ``show wlan`` family (CLI-Bank, MD-first).

    Reference: [show wlan](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-wlan.htm)

    HPE documents the family under Mobility Conductor; this tool still **prefers a
    managed device** when ``md_ips`` are configured (first member, or ``md_ip``),
    matching the operational MM+MD workflow used elsewhere (``aos8_clients``).

    Variants mirror CLI-Bank subcommands, including:
      * ``virtual_ap`` (default), ``wlan_profiles`` (bare ``show wlan`` index)
      * ``ssid_profile`` / ``he_ssid_profile`` / ``ht_ssid_profile`` — pass
        ``profile_name`` (defaults to ``default`` when omitted)
      * ``hotspot``, ``sae_profile``, ``dot11k_profile``, ``dot11r_profile``
      * ``rrm_ie_profile``, ``six_ghz_rrm_ie_profile``, ``anyspot_profile``
      * ``edca_parameters_profile``, ``mu_edca_parameters_profile``
      * ``traffic_management_profile``, ``wmm_traffic_management_profile``
      * ``bcn_rpt_req_profile``, ``tsm_req_profile``, ``client_wlan_profile``

    Short aliases (e.g. ``vap``, ``ssid``, ``wmm_tm``) resolve via ``aos8_catalog``.
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
        md_ip=md_ip,
    )


@mcp.tool()
async def aos8_log(
    session_id: str,
    variant: str = "all",
    tail: int | None = None,
    match: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = False,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """Controller log views — ``show log [<category>] [all] [<N>]`` with built-in filtering.

    AOS 8 supports two device-side filters that this tool composes for you:
      * ``tail=<N>``   — appends ``<N>`` to the CLI so the controller returns
        only the last N lines. This is much cheaper than fetching the entire
        log buffer and trimming server-side (which is what ``max_lines`` does).
      * ``match=<token>`` — shortcut for ``cli_suffix='| include <token>'``;
        the token has any ``|`` characters stripped to keep the include-regex
        sane. Both ``tail`` and ``match`` can be combined.

    Example: ``aos8_log(sid, "security", tail=500, match="auth")`` invokes
    ``show log security all 500 | include auth``.

    Variants (call ``aos8_catalog(domain='log')`` for the full list — mirrors
    every official ``show log`` subcommand):
      * ``all`` (default)
      * ``errorlog`` / ``security`` / ``system`` / ``user`` / ``wireless``
      * ``ap_debug`` / ``arm`` / ``arm_user_debug`` / ``network`` /
        ``peer_debug`` / ``user_debug``  (hyphenated names also accepted)

    Output: ``normalized`` contains the parsed log lines (with head/tail
    summaries); ``max_lines`` applies a final server-side cap (defaulting to
    ``AOS8_LOG_DEFAULT_TAIL`` = 200) so even an unbounded fetch stays
    LLM-friendly.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}

    override = _coerce_optional_str(command_override)
    suf = _coerce_optional_str(cli_suffix)
    match_token = _coerce_optional_str(match)
    v = _coerce_optional_str(variant)

    effective_max_lines = max_lines if max_lines is not None else _DEFAULT_LOG_TAIL

    if tail is not None and tail <= 0:
        return {"ok": False, "error": "tail must be a positive integer."}

    if override:
        base_cmd = override
        cache_tier: CacheTier = "realtime"
        normalizer: NormalizerHint = "log_text"
        variant_used: str | None = None
    else:
        try:
            preset = resolve_preset("log", v)
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        base_cmd = preset.command
        cache_tier = preset.cache_tier
        normalizer = preset.normalizer
        variant_used = preset.key

    if tail is not None:
        base_cmd = f"{base_cmd} {int(tail)}"

    if match_token:
        token = _escape_for_include(match_token)
        if not token:
            return {"ok": False, "error": "match cannot be empty or pipe-only."}
        include_clause = f"| include {token}"
        suf = f"{include_clause} {suf}".strip() if suf else include_clause

    cmd = _compose_command(base_cmd, suf)
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}

    try:
        raw = await store.show_with_mm_then_md_fallback(
            sid, cmd, use_cache=use_cache, cache_tier=cache_tier
        )
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}

    enriched = await _with_normalize(raw, normalizer)
    enriched = apply_truncation(
        enriched, max_lines=effective_max_lines, max_rows=None
    )
    enriched["domain"] = "log"
    if variant_used:
        enriched["variant"] = variant_used
        enriched["cache_tier"] = cache_tier
    return {"ok": True, **enriched}


@mcp.tool()
async def aos8_system(
    session_id: str,
    variant: str = "version",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Platform health & identification for the local controller (MM by default).

    Identity / version (static, cached longer):
      * ``version`` (default) — short ``show version`` banner.
      * ``switchinfo``        — comprehensive ``show switchinfo`` dump (hostname,
                                system time, OS version, uptime, reboot cause,
                                management IP, switch role, save/crash status).
                                **Best one-shot snapshot for "what is this box?"**
      * ``switch_software``   — ``show switch software`` (compile date, build,
                                supervisor card details).
      * ``switch_ip`` / ``hostname`` / ``clock`` / ``uptime`` / ``boot`` /
        ``image_version`` / ``inventory``

    Capacity & health (realtime / near-realtime):
      * ``cpuload`` / ``memory`` / ``storage``

    Licensing:
      * ``license`` / ``license_summary``

    Call ``aos8_catalog(domain='system')`` to list every variant. Note that
    ``show switches`` and ``show switches state ...`` (hierarchy-wide views)
    live under ``aos8_controllers``; this tool is the local-box view.

    ``max_lines`` caps text dumps (``switchinfo``/``switch_software`` are
    multi-line); ``max_rows`` caps table-style outputs (``inventory``,
    ``license``). Both are optional — system commands are usually short.
    """
    return await _run_domain(
        session_id=session_id,
        domain="system",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        use_cache=use_cache,
        max_lines=max_lines,
        max_rows=max_rows,
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
    profile_name: str | None = None,
    arg: str | None = None,
    md_ip: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """AAA authentication servers, profiles, and runtime diagnostics (MD-first).

    When ``md_ips`` are configured on the session, ``show aaa …`` commands are
    sent to the first MD immediately (or to ``md_ip`` when set), consistent with
    ``aos8_clients`` / ``aos8_wlan``.

    Aligns with CLI-Bank ``show aaa …`` families (authentication-server,
    authentication dot1x/mac/captive-portal/stateful-dot1x, state messages).

    **Common variants** (see ``aos8_catalog(domain='aaa')`` for aliases):
      * ``state_messages`` (default) — recent AAA state (good with
        ``cli_suffix='| include …'``)
      * ``authentication_server_all`` / alias ``auth_servers`` — all auth servers
      * ``authentication_server_radius`` / ``radius`` — RADIUS server list;
        ``arg='<name>'`` for one server
      * ``authentication_server_radius_statistics`` — RADIUS counters
      * ``authentication_server_radius_radsec_status`` — RadSec TLS status
      * ``authentication_dot1x`` / ``dot1x`` — 802.1X profiles;
        ``profile_name='<profile>'`` for detail
      * ``authentication_dot1x_countermeasures`` — dot1x countermeasures
      * ``authentication_mac`` / ``mac_auth`` — MAC auth profiles;
        optional ``profile_name``
      * ``authentication_captive_portal`` / ``cp`` — captive portal profiles;
        optional ``profile_name``
      * ``authentication_stateful_dot1x`` — stateful 802.1X summary
      * ``authentication_stateful_dot1x_config_entries`` — stateful-dot1x config rows

    ``profile_name`` applies only to dot1x/mac/captive-portal list presets.
    ``arg`` appends trailing CLI tokens (e.g. RADIUS server name). Overrides ignore
    preset composition — use ``command_override`` for ad-hoc ``show aaa …``.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}

    suf = _coerce_optional_str(cli_suffix)
    override = _coerce_optional_str(command_override)
    v = _coerce_optional_str(variant)
    md_eff = _coerce_optional_str(md_ip)

    effective_max_lines = max_lines if max_lines is not None else _DEFAULT_LOG_TAIL
    effective_max_rows = max_rows if max_rows is not None else _DEFAULT_TABLE_CAP

    if override:
        cmd = _compose_command(override, suf)
        err = _validate_show_command(cmd)
        if err:
            return {"ok": False, "error": err}
        try:
            raw, bias_note = await _fetch_show_with_md_first_bias(
                sid,
                cmd,
                use_cache=use_cache,
                cache_tier="near_realtime",
                md_ip=md_eff,
                md_bias_domain="aaa",
            )
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        except ArubaHttpError as e:
            return {"ok": False, "error": str(e)}
        enriched = await _with_normalize(raw, "generic")
        if bias_note:
            prev = enriched.get("note")
            enriched["note"] = f"{prev}\n{bias_note}" if prev else bias_note
        enriched = apply_truncation(
            enriched, max_lines=effective_max_lines, max_rows=effective_max_rows
        )
        return {"ok": True, "domain": "aaa", **enriched}

    try:
        preset = resolve_preset("aaa", v)
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    extra_cli = _compose_aaa_extra_cli(
        preset.key,
        profile_name=profile_name,
        arg=arg,
    )

    result = await _execute_preset(
        sid,
        preset,
        cli_suffix=suf,
        extra_cli=extra_cli,
        use_cache=use_cache,
        max_lines=effective_max_lines,
        max_rows=effective_max_rows,
        md_ip=md_eff,
        md_bias_domain="aaa",
    )
    if result.get("ok"):
        result["domain"] = "aaa"
    return result


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
    arg: str | None = None,
    md_ip: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """RF monitoring plus RF profile configuration (official ``show rf`` family, MD-first).

    When ``md_ips`` are configured, ``show ap …`` and ``show rf …`` presets go to
    the first MD (or ``md_ip``) without a wasted MM round-trip.

    **Operational monitoring** (runtime near-realtime views — mostly ``show ap …``):
      * ``arm_rf_summary`` (default) — per-radio channel / power / noise
      * ``monitor_stats`` — air monitor statistics
      * ``bss_table`` / ``radio_summary`` / ``radio_table``
      * ``channel_summary`` — ARM scan-times

    **RF configuration** on Mobility Conductor (static ``show rf …``, CLI-Bank
    ``sh-rf.htm``):
      * ``rf_am_scan_profile`` — AM scan profile
      * ``rf_arm_profile`` — ARM profile (also callable as variant ``arm-profile`` / ``arm_profile``)
      * ``rf_arm_rf_domain_profile`` — ARM RF domain profile
      * ``rf_dot11_60ghz_radio_profile`` / ``rf_dot11_6ghz_radio_profile``
      * ``rf_dot11a_radio_profile`` / ``rf_dot11a_secondary_radio_profile`` /
        ``rf_dot11g_radio_profile``
      * ``rf_event_thresholds_profile`` / ``rf_ht_radio_profile`` /
        ``rf_optimization_profile`` / ``rf_spectrum_profile``

    Pass ``arg`` to append a profile name or other trailing CLI tokens, e.g.
    ``variant='rf_arm_profile', arg='default'`` → ``show rf arm-profile default``.
    Use ``aos8_catalog(domain='rf')`` for the full preset list and short aliases.
    """
    return await _run_domain(
        session_id=session_id,
        domain="rf",
        variant=variant,
        cli_suffix=cli_suffix,
        command_override=command_override,
        extra_cli=arg,
        use_cache=use_cache,
        max_rows=max_rows,
        default_max_rows=_DEFAULT_TABLE_CAP,
        md_ip=md_ip,
    )


@mcp.tool()
async def aos8_airmatch(
    session_id: str,
    variant: str = "optimization",
    ap_name: str | None = None,
    arg: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
    max_lines: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """AirMatch read-only views — ``show airmatch …`` on Mobility Conductor.

    Covers CLI-Bank AirMatch families: solution list/history, optimization jobs,
    profile, AP partition, and debug (apinfo, history, db-dump, optimization,
    client-history).

    Common variants (see ``aos8_catalog(domain='airmatch')``):
      * ``optimization`` (default) — recent jobs; ``arg='14'`` for solution #14 detail
      * ``solution_list_all`` — all radios' applied solution rows
      * ``solution`` — scoped solution; use ``ap_name=…`` or ``arg='band 5 GHz'`` /
        ``'mac <radiomac>'`` / ``'switch-ip <ip>'``
      * ``profile`` — AirMatch profile parameters
      * ``ap_partition_status_detail`` — cluster partition detail (alias ``partition``)
      * ``debug_apinfo`` / ``debug_history`` / ``debug_client_history`` —
        pass ``ap_name`` or ``arg='mac …'`` / ``'ethmac …'`` / ``'radiomac …'``
      * ``debug_db_dump_status`` — DB dump status
      * ``debug_optimization`` — debug optimization list/detail; ``arg`` examples:
        ``last``, ``77``, ``advanced partition``, ``77 sort-by band descending``

    Short aliases: ``opt``, ``solution_all``, ``partition``, ``dbg_opt``, …

    ``ap_name`` auto-expands to ``ap-name <name>`` only for ``solution`` and
    the ``debug_*`` AP-scoped presets above; everything else uses ``arg`` only.
    """
    sid = _coerce_optional_str(session_id)
    if not sid:
        return {"ok": False, "error": "session_id missing or invalid."}

    suf = _coerce_optional_str(cli_suffix)
    override = _coerce_optional_str(command_override)
    v = _coerce_optional_str(variant)

    effective_max_lines = max_lines
    effective_max_rows = max_rows if max_rows is not None else _DEFAULT_TABLE_CAP

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
        return {"ok": True, "domain": "airmatch", **enriched}

    try:
        preset = resolve_preset("airmatch", v)
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    base_cmd = _compose_airmatch_command(
        preset.key,
        preset.command,
        ap_name=ap_name,
        arg=arg,
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
    enriched["domain"] = "airmatch"
    return {"ok": True, **enriched}


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
      * ``utilization`` / alias ``cpu`` — **datapath CPU utilization by CPU ID**
        (1 s / 4 s / 64 s averages; CLI-Bank ``show datapath utilization``). Pair with
        ``debug_performance`` when digging deeper into per-CPU datapath behavior.
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
    sid: str,
    steps: list[tuple[str, ShowPreset, str | None]],
    *,
    md_bias_domains: list[str | None] | None = None,
) -> list[dict[str, Any]]:
    """Run several presets in parallel; return one summary dict per step.

    ``md_bias_domains`` (optional, same length as ``steps``) selects MD-first
    routing for composite helpers that mix domains (e.g. ``aaa`` / ``rf``).
    """
    n = len(steps)
    domains = list(md_bias_domains) if md_bias_domains else [None] * n
    if len(domains) < n:
        domains.extend([None] * (n - len(domains)))
    elif len(domains) > n:
        domains = domains[:n]

    coros = [
        _execute_preset(
            sid,
            preset,
            cli_suffix=suffix,
            use_cache=True,
            max_lines=_DEFAULT_LOG_TAIL,
            max_rows=_DEFAULT_TABLE_CAP,
            md_bias_domain=domains[i],
        )
        for i, (_, preset, suffix) in enumerate(steps)
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
    include_rf: bool = True,
) -> dict[str, Any]:
    """Run several ``show ap *`` queries for a single AP and aggregate the highlights.

    Steps executed in parallel:
      * ``show ap database`` (filtered)         — registration / status / flags
      * ``show ap active`` (filtered)           — currently active radios
      * ``show ap radio-summary`` (filtered)    — per-radio channel / power
      * (optional) ``show ap arm rf-summary`` (filtered) — ARM RF detail per radio
        (channel / power / noise); aligns with the operational side of RF / ARM
        troubleshooting referenced alongside the ``show rf`` profile family in
        CLI-Bank ``sh-rf.htm`` (profile config itself is ``aos8_rf`` with
        ``rf_*`` variants, not AP-scoped).
      * ``show ap bss-table`` (filtered)        — BSSIDs and load
      * ``show global-user-table list`` (filtered) — associated users
      * (optional) recent ``show log all`` lines mentioning the AP

    Set ``include_rf=False`` to skip the ARM RF-summary step on very slow MM.
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
    ]
    if include_rf:
        steps.append(
            ("arm_rf_summary", resolve_preset("rf", "arm_rf_summary"), inc),
        )
    steps.extend(
        [
            ("bss_table", resolve_preset("aps", "bss_table"), inc),
            ("clients_on_ap", resolve_preset("clients", "global_user_table_list"), inc),
        ]
    )
    if include_log_tail:
        steps.append(("recent_log", resolve_preset("log", "all"), inc))

    md_bias: list[str | None] = [None, None, None]
    if include_rf:
        md_bias.append("rf")
    md_bias.extend([None, None])
    if include_log_tail:
        md_bias.append(None)

    results = await _gather_steps(sid, steps, md_bias_domains=md_bias)
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

    md_bias = [None, None, None, "aaa"]
    if include_log_tail:
        md_bias.append(None)

    results = await _gather_steps(sid, steps, md_bias_domains=md_bias)
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
