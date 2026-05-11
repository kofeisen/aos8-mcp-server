"""FastMCP entry: Streamable HTTP + Aruba session + domain show tools."""

from __future__ import annotations

import os
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
    NormalizerHint,
    ap_variant_catalog,
    get_spec,
    normalize_wlan_variant_key,
    resolve_ap_variant,
    resolve_wlan_variant,
    wlan_variant_catalog,
)

_HOST = os.environ.get("AOS8_MCP_HOST", "0.0.0.0")
_PORT = int(os.environ.get("AOS8_MCP_PORT", "8765"))
_CACHE_TTL = float(os.environ.get("AOS8_CACHE_TTL_SECONDS", "60"))
# Streamable HTTP：默认 stateful（每会话需 mcp-session-id）。裸 GET /mcp 会 400，属协议顺序问题。
# 若 Open WebUI 等客户端握手异常，可设 AOS8_MCP_STATELESS_HTTP=true（每请求独立 transport，无会话头要求）。
_STATELESS_HTTP = os.environ.get("AOS8_MCP_STATELESS_HTTP", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

store.cache.configure_ttl(_CACHE_TTL)

mcp = FastMCP(
    "aos8-mcp-server",
    instructions=(
        "Aruba AOS 8.x 只读 MCP：先 aos8_session_create_from_config（本地 aos8.devices.yaml）"
        "或 aos8_session_create 登录 MM，再调用各领域 show；结束后 aos8_session_destroy。"
        "默认在 MM 执行；若提示 conductor 不可用会自动按配置的 MD 顺序尝试。"
        "建议在控制器上配置 #no paging 以避免分页。支持 show 后接 | include / exclude / begin 等过滤。"
        "aos8_aps 支持 variant 选择多种 show ap 子命令；aos8_ap_show_variants 可列出全部键。"
        "aos8_wlan 支持 variant 选择多种 show wlan 子命令；profile_name 可选；aos8_wlan_show_variants 列出键。"
    ),
    host=_HOST,
    port=_PORT,
    streamable_http_path="/mcp",
    stateless_http=_STATELESS_HTTP,
)


def _compose_command(base: str, cli_suffix: str | None) -> str:
    base = base.strip()
    if not cli_suffix:
        return base
    suf = cli_suffix.strip()
    if suf.startswith("|"):
        return f"{base} {suf}"
    return f"{base} | {suf}"


def _validate_show_command(cmd: str) -> str | None:
    c = cmd.strip()
    if "\n" in c or "\r" in c:
        return "命令中不允许换行。"
    low = c.lower()
    if not low.startswith("show "):
        return "仅允许 show 命令（须以 'show ' 开头）。"
    return None


async def _with_norm(
    result: dict[str, Any],
    hint: NormalizerHint,
) -> dict[str, Any]:
    out = dict(result)
    out["normalized"] = normalize_payload(hint, result.get("raw"))
    return out


@mcp.tool()
async def aos8_session_create_from_config(config_path: str = "") -> dict[str, Any]:
    """从本地 YAML 读取 MM/MD 的 IP 与密码并登录（推荐日常使用，避免在 Chat 里粘贴密码）。

    默认读取当前工作目录下的 ``aos8.devices.yaml``，或环境变量 ``AOS8_DEVICES_CONFIG`` 指向的文件。
    可将 ``aos8.devices.example.yaml`` 复制为 ``aos8.devices.yaml`` 后填写。

    ``config_path`` 非空时优先使用该路径（支持绝对路径或相对当前工作目录）。
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
        return {"ok": False, "error": f"配置文件字段无效: {e}"}
    gr = login_body.get("_global_result") if isinstance(login_body, dict) else {}
    cfg_path_used = str(path.resolve()) if path else str(default_devices_config_path())
    return {
        "ok": True,
        "session_id": sid,
        "config_path": cfg_path_used,
        "mm_ip": cfg.mm.ip.strip(),
        "md_ips": md_ips,
        "login_status_str": gr.get("status_str") if isinstance(gr, dict) else None,
        "hint": "凭据从配置文件读取后仅用于登录；会话仍仅存于本进程内存，用毕请 aos8_session_destroy。",
    }


@mcp.tool()
async def aos8_session_create(
    mm_ip: str,
    username: str,
    password: str,
    md_ips: list[str] | None = None,
    verify_ssl: bool = False,
) -> dict[str, Any]:
    """登录 MM，建立可复用的服务端会话；请在排障结束后调用 aos8_session_destroy。

    verify_ssl：与 httpx 的 verify 一致；False 表示不校验 TLS 证书（等价 curl --insecure），
    内网自签证书场景常用；True 为严格校验。

    若希望不把密码写进对话，请改用 ``aos8_session_create_from_config`` + 本地 ``aos8.devices.yaml``。
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
        "hint": "凭据与会话仅保存在本进程内存中；请在使用完毕后调用 aos8_session_destroy。",
    }


@mcp.tool()
async def aos8_session_destroy(session_id: str) -> dict[str, Any]:
    """注销 MM 及已登录的 MD，并清除与该 session 关联的 show 缓存。"""
    try:
        await store.destroy(session_id)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "session_id": session_id}


@mcp.tool()
async def aos8_show(
    session_id: str,
    command: str,
    target: Literal["mm", "md"] = "mm",
    md_ip: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """执行任意只读 show；target=mm 时沿用「MM 优先、必要时按 md_ips 回落 MD」策略。"""
    cmd = command.strip()
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}
    try:
        raw = await store.show_on_target(session_id, cmd, target=target, md_ip=md_ip, use_cache=use_cache)
        return {"ok": True, **await _with_norm(raw, "generic")}
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}


async def _domain_show(
    session_id: str,
    domain: str,
    cli_suffix: str | None,
    command_override: str | None,
    extra_hint: NormalizerHint | None = None,
    *,
    wlan_variant: str | None = None,
    wlan_profile_name: str | None = None,
    ap_variant: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    spec = get_spec(domain)
    hint: NormalizerHint = extra_hint or spec.normalizer
    if command_override and command_override.strip():
        base = command_override.strip()
    elif domain == "wlan" and wlan_variant:
        try:
            base, hint = resolve_wlan_variant(wlan_variant)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if wlan_profile_name and wlan_profile_name.strip():
            base = f"{base} {wlan_profile_name.strip()}"
        else:
            vk = normalize_wlan_variant_key(wlan_variant)
            if vk in ("ssid_profile", "he_ssid_profile", "ht_ssid_profile"):
                base = f"{base} default"
    elif domain == "aps" and ap_variant:
        try:
            base, hint = resolve_ap_variant(ap_variant)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    else:
        base = spec.default_command
    cmd = _compose_command(base, cli_suffix)
    err = _validate_show_command(cmd)
    if err:
        return {"ok": False, "error": err}
    try:
        raw = await store.show_with_mm_then_md_fallback(session_id, cmd, use_cache=use_cache)
        out = {"ok": True, "domain": domain, **await _with_norm(raw, hint)}
        if domain == "aps" and ap_variant and not (command_override and command_override.strip()):
            out["ap_variant"] = ap_variant.strip()
        if domain == "wlan" and wlan_variant and not (command_override and command_override.strip()):
            out["wlan_variant"] = wlan_variant.strip()
        return out
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ArubaHttpError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def aos8_controllers(
    session_id: str,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """默认 show switches（控制器 / conductor 视图）。"""
    return await _domain_show(session_id, "controllers", cli_suffix, command_override, use_cache=use_cache)


@mcp.tool()
async def aos8_clients(
    session_id: str,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """默认 show global-user-table list。"""
    return await _domain_show(session_id, "clients", cli_suffix, command_override, use_cache=use_cache)


@mcp.tool()
async def aos8_ap_show_variants() -> dict[str, Any]:
    """列出 aos8_aps 支持的 variant：每项含 command 与 description（与 AOS8 CLI 说明一致）。"""
    return {"ok": True, "variants": ap_variant_catalog()}


@mcp.tool()
async def aos8_aps(
    session_id: str,
    variant: str = "database",
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """执行 show ap 子命令。variant 为注册键（如 database、ap_lacp_striping_ip、denylist_clients）；默认 database。

    各 variant 的 CLI 与英文说明见 **aos8_ap_show_variants**；定义在 ``aos8_mcp/show_registry.py`` 的 ``AP_SHOW_VARIANTS``。
    仍可通过 command_override 传入任意 ``show ap ...``（此时忽略 variant）。
    """
    ap_v = None if (command_override and command_override.strip()) else variant
    return await _domain_show(
        session_id,
        "aps",
        cli_suffix,
        command_override,
        ap_variant=ap_v,
        use_cache=use_cache,
    )


@mcp.tool()
async def aos8_log(
    session_id: str,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """默认 show log all；大日志务必配合 cli_suffix 使用 | include / exclude。"""
    return await _domain_show(session_id, "log", cli_suffix, command_override, use_cache=use_cache)


@mcp.tool()
async def aos8_wlan_show_variants() -> dict[str, Any]:
    """列出 aos8_wlan 支持的 variant：每项含 command 与 description（格式与 aos8_ap_show_variants 一致）。"""
    return {"ok": True, "variants": wlan_variant_catalog()}


@mcp.tool()
async def aos8_wlan(
    session_id: str,
    variant: str = "virtual_ap",
    profile_name: str | None = None,
    cli_suffix: str | None = None,
    command_override: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """执行 show wlan 子命令。variant 见 aos8_wlan_show_variants；需要具体 profile 名时传 profile_name（如 default）。

    仍可用 command_override 传入完整 ``show wlan ...``（此时忽略 variant / profile_name）。
    """
    wlan_v = None if (command_override and command_override.strip()) else variant
    return await _domain_show(
        session_id,
        "wlan",
        cli_suffix,
        command_override,
        wlan_variant=wlan_v,
        wlan_profile_name=profile_name,
        use_cache=use_cache,
    )


def run() -> None:
    mcp.run(transport="streamable-http")
