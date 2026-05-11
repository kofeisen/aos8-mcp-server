"""Server-side Aruba login sessions (B): one MCP session_id, many tool calls, then destroy."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any

from aos8_mcp.aruba_client import ArubaDeviceClient, ArubaHttpError, _looks_like_not_on_conductor
from aos8_mcp.cache import ShowResultCache


@dataclass
class Aos8ServerSession:
    session_id: str
    mm_host: str
    username: str
    password: str
    verify_ssl: bool
    md_ips: list[str] = field(default_factory=list)
    """按顺序尝试的 MD 管理 IP 列表。"""
    md_logins: dict[str, tuple[str, str]] = field(default_factory=dict)
    """各 MD IP 对应的 (username, password)；缺省条目时回退为 MM 的账号。"""
    mm_client: ArubaDeviceClient | None = None
    md_clients: dict[str, ArubaDeviceClient] = field(default_factory=dict)
    _md_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def login_mm(self) -> dict[str, Any]:
        self.mm_client = ArubaDeviceClient(self.mm_host, self.verify_ssl)
        return await self.mm_client.login(self.username, self.password)

    def _md_credentials(self, md_ip: str) -> tuple[str, str]:
        return self.md_logins.get(md_ip, (self.username, self.password))

    async def ensure_md_client(self, md_ip: str) -> ArubaDeviceClient:
        async with self._md_lock:
            if md_ip in self.md_clients:
                return self.md_clients[md_ip]
            user, pwd = self._md_credentials(md_ip)
            cli = ArubaDeviceClient(md_ip, self.verify_ssl)
            await cli.login(user, pwd)
            self.md_clients[md_ip] = cli
            return cli

    async def close_all(self) -> None:
        if self.mm_client:
            try:
                await self.mm_client.logout()
            finally:
                await self.mm_client.aclose()
            self.mm_client = None
        for ip, cli in list(self.md_clients.items()):
            try:
                await cli.logout()
            finally:
                await cli.aclose()
            del self.md_clients[ip]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Aos8ServerSession] = {}
        self._lock = asyncio.Lock()
        self.cache = ShowResultCache()

    async def create(
        self,
        mm_host: str,
        username: str,
        password: str,
        md_ips: list[str] | None,
        verify_ssl: bool,
        md_logins: dict[str, tuple[str, str]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        sid = secrets.token_urlsafe(18)
        ips = [ip.strip() for ip in (md_ips or []) if ip.strip()]
        logins: dict[str, tuple[str, str]] = dict(md_logins or {})
        for ip in ips:
            logins.setdefault(ip, (username, password))
        sess = Aos8ServerSession(
            session_id=sid,
            mm_host=mm_host.strip(),
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            md_ips=ips,
            md_logins=logins,
        )
        login_body = await sess.login_mm()
        async with self._lock:
            self._sessions[sid] = sess
        return sid, login_body

    async def destroy(self, session_id: str) -> None:
        async with self._lock:
            sess = self._sessions.pop(session_id, None)
        if sess:
            await sess.close_all()
        await self.cache.invalidate_session(session_id)

    async def get(self, session_id: str) -> Aos8ServerSession:
        async with self._lock:
            sess = self._sessions.get(session_id)
        if not sess:
            raise KeyError(f"Unknown session_id {session_id!r}; create a session first.")
        return sess

    async def show_with_mm_then_md_fallback(
        self,
        session_id: str,
        command: str,
        use_cache: bool,
    ) -> dict[str, Any]:
        sess = await self.get(session_id)
        if not sess.mm_client or not sess.mm_client.tokens:
            raise ArubaHttpError("MM session not logged in")

        cache_key = (session_id, sess.mm_host, command)
        if use_cache:
            hit = await self.cache.get(cache_key)
            if hit is not None:
                out = dict(hit)
                out["from_cache"] = True
                return out

        status, payload = await sess.mm_client.show_command(command)
        result = _build_tool_result(
            target_host=sess.mm_host,
            command=command,
            http_status=status,
            raw=payload,
            executed_on="mm",
            md_ip_used=None,
            conductor_rejected=_looks_like_not_on_conductor(payload),
        )

        if not result["conductor_rejected"]:
            await self.cache.set(cache_key, {**result, "from_cache": False})
            return result

        mm_skip_msg = (
            "MM 返回该命令在 conductor 上不可用，已按配置尝试在 MD 上执行（如有）。"
        )
        if not sess.md_ips:
            result["note"] = (
                "未配置 MD 列表，无法自动落到 MD。请在会话创建时传入 md_ips，"
                "或使用本地 aos8.devices.yaml / aos8_session_create_from_config，"
                "或使用 aos8_show 指定 target='md'。"
            )
            result["fallback_attempts"] = []
            await self.cache.set(cache_key, {**result, "from_cache": False})
            return result

        attempts: list[dict[str, Any]] = []
        for md_ip in sess.md_ips:
            try:
                md_cli = await sess.ensure_md_client(md_ip)
                st, pl = await md_cli.show_command(command)
                att = {"md_ip": md_ip, "http_status": st, "still_conductor_msg": _looks_like_not_on_conductor(pl)}
                attempts.append(att)
                if not att["still_conductor_msg"]:
                    result_md = _build_tool_result(
                        target_host=md_ip,
                        command=command,
                        http_status=st,
                        raw=pl,
                        executed_on="md",
                        md_ip_used=md_ip,
                        conductor_rejected=False,
                    )
                    result_md["mm_skipped_reason"] = mm_skip_msg
                    result_md["fallback_attempts"] = attempts
                    ckey_md = (session_id, md_ip, command)
                    await self.cache.set(ckey_md, {**result_md, "from_cache": False})
                    return result_md
            except Exception as ex:  # noqa: BLE001
                attempts.append({"md_ip": md_ip, "error": str(ex)})

        result["note"] = "所有已配置 MD 上仍无法成功执行该命令（或仍提示 conductor 限制）。"
        result["fallback_attempts"] = attempts
        await self.cache.set(cache_key, {**result, "from_cache": False})
        return result

    async def show_on_target(
        self,
        session_id: str,
        command: str,
        target: str,
        md_ip: str | None,
        use_cache: bool,
    ) -> dict[str, Any]:
        sess = await self.get(session_id)
        if target == "mm":
            return await self.show_with_mm_then_md_fallback(session_id, command, use_cache=use_cache)
        if target != "md":
            raise ValueError("target must be 'mm' or 'md'")
        if not md_ip:
            raise ValueError("md_ip is required when target='md'")
        md_cli = await sess.ensure_md_client(md_ip.strip())
        cache_key = (session_id, md_ip.strip(), command)
        if use_cache:
            hit = await self.cache.get(cache_key)
            if hit is not None:
                out = dict(hit)
                out["from_cache"] = True
                return out
        status, payload = await md_cli.show_command(command)
        result = _build_tool_result(
            target_host=md_ip.strip(),
            command=command,
            http_status=status,
            raw=payload,
            executed_on="md",
            md_ip_used=md_ip.strip(),
            conductor_rejected=_looks_like_not_on_conductor(payload),
        )
        await self.cache.set(cache_key, {**result, "from_cache": False})
        return result


def _build_tool_result(
    *,
    target_host: str,
    command: str,
    http_status: int,
    raw: Any,
    executed_on: str,
    md_ip_used: str | None,
    conductor_rejected: bool,
) -> dict[str, Any]:
    return {
        "target_host": target_host,
        "command": command,
        "http_status": http_status,
        "raw": raw,
        "executed_on": executed_on,
        "md_ip_used": md_ip_used,
        "conductor_rejected": conductor_rejected,
        "from_cache": False,
    }


store = SessionStore()
