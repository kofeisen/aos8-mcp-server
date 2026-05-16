"""Server-side Aruba login sessions: one MCP session_id, many tool calls, then destroy.

A session owns:
  * one MM HTTP client (always required) and
  * one HTTP client per configured MD management IP.

On creation the store logs into the MM and **every** configured MD in parallel,
so ``UIDARUBA`` / CSRF tokens exist for each device before any data tool runs.
Each ``show`` call (unless served from cache) re-authenticates as needed, then
optionally logs out again after the HTTP request to avoid exhausting concurrent
API sessions on the controllers (see ``AOS8_LOGOUT_AFTER_EACH_TOOL``).

The store also hosts the shared :class:`ShowResultCache` so cached entries are
purged when a session is destroyed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from aos8_mcp.aruba_client import (
    ArubaAuthExpired,
    ArubaDeviceClient,
    ArubaHttpError,
    configured_uidaruba_ttl_seconds,
    _looks_like_not_on_conductor,
)
from aos8_mcp.cache import CacheTier, ShowResultCache


log = logging.getLogger("aos8_mcp.session_store")

_LOGOUT_AFTER_EACH_TOOL = os.environ.get("AOS8_LOGOUT_AFTER_EACH_TOOL", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


@dataclass
class Aos8ServerSession:
    session_id: str
    mm_host: str
    username: str
    password: str
    verify_ssl: bool
    md_ips: list[str] = field(default_factory=list)
    """Ordered list of MD management IPs to try on conductor fallback."""
    md_logins: dict[str, tuple[str, str]] = field(default_factory=dict)
    """Per-MD ``(username, password)`` overrides; missing entries reuse the MM credentials."""
    mm_client: ArubaDeviceClient | None = None
    md_clients: dict[str, ArubaDeviceClient] = field(default_factory=dict)
    created_at_monotonic: float = field(default_factory=time.monotonic)
    last_activity_monotonic: float = field(default_factory=time.monotonic)
    _md_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        """Mark the session as active. Called on every successful tool invocation."""
        self.last_activity_monotonic = time.monotonic()

    def idle_seconds(self, now: float | None = None) -> float:
        return (now if now is not None else time.monotonic()) - self.last_activity_monotonic

    async def login_mm(self) -> dict[str, Any]:
        self.mm_client = ArubaDeviceClient(self.mm_host, self.verify_ssl)
        return await self.mm_client.login(self.username, self.password)

    def _md_credentials(self, md_ip: str) -> tuple[str, str]:
        return self.md_logins.get(md_ip, (self.username, self.password))

    async def ensure_md_client(self, md_ip: str) -> ArubaDeviceClient:
        """Return a logged-in client for ``md_ip``, creating it in parallel with other MDs."""
        md_ip = md_ip.strip()
        async with self._md_lock:
            existing = self.md_clients.get(md_ip)
        if existing is not None:
            return existing
        user, pwd = self._md_credentials(md_ip)
        cli = ArubaDeviceClient(md_ip, self.verify_ssl)
        await cli.login(user, pwd)
        async with self._md_lock:
            dup = self.md_clients.get(md_ip)
            if dup is not None:
                await cli.aclose()
                return dup
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

    def describe(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "session_id": self.session_id,
            "mm_host": self.mm_host,
            "mm_logged_in": bool(self.mm_client and self.mm_client.is_authenticated),
            "md_ips": list(self.md_ips),
            "md_clients": [
                {"ip": ip, "logged_in": cli.is_authenticated}
                for ip, cli in self.md_clients.items()
            ],
            "verify_ssl": self.verify_ssl,
            "age_seconds": round(now - self.created_at_monotonic, 1),
            "idle_seconds": round(self.idle_seconds(now), 1),
            "uidaruba_ttl_seconds": int(configured_uidaruba_ttl_seconds()),
            "logout_after_each_tool": _LOGOUT_AFTER_EACH_TOOL,
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Aos8ServerSession] = {}
        self._lock = asyncio.Lock()
        self.cache = ShowResultCache()
        # Idle-session reaper (disabled by default; configure_idle_reap to enable).
        self._idle_timeout: float = 0.0
        self._reap_interval: float = 60.0
        self._reaper_task: asyncio.Task[None] | None = None
        self._reaper_started_loop: asyncio.AbstractEventLoop | None = None

    # ----- idle reaper -----
    def configure_idle_reap(
        self,
        idle_timeout_seconds: float,
        scan_interval_seconds: float = 60.0,
    ) -> None:
        """Set idle-session reap policy. ``idle_timeout_seconds <= 0`` disables it."""
        self._idle_timeout = max(0.0, idle_timeout_seconds)
        self._reap_interval = max(1.0, scan_interval_seconds)

    @property
    def idle_timeout(self) -> float:
        return self._idle_timeout

    @property
    def reap_interval(self) -> float:
        return self._reap_interval

    @property
    def logout_after_each_tool(self) -> bool:
        """When true, each uncached ``show`` ends with ``/v1/api/logout`` to free controller slots."""
        return _LOGOUT_AFTER_EACH_TOOL

    def _maybe_start_reaper(self) -> None:
        """Start the background reaper lazily, bound to the running event loop."""
        if self._idle_timeout <= 0:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._reaper_task and not self._reaper_task.done():
            if self._reaper_started_loop is loop:
                return
            # Loop changed (e.g. in tests). Cancel old task and restart.
            self._reaper_task.cancel()
        self._reaper_started_loop = loop
        self._reaper_task = loop.create_task(self._reaper_loop())

    async def _reaper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._reap_interval)
                try:
                    await self._reap_once()
                except Exception:  # noqa: BLE001
                    log.exception("Idle reaper iteration failed")
        except asyncio.CancelledError:
            pass

    async def _reap_once(self, now: float | None = None) -> list[str]:
        """Drop every session whose idle time exceeds the configured timeout.

        Returned list contains the reaped ``session_id`` values, primarily for tests.
        """
        if self._idle_timeout <= 0:
            return []
        when = now if now is not None else time.monotonic()
        async with self._lock:
            stale = [
                sid
                for sid, sess in self._sessions.items()
                if sess.idle_seconds(when) > self._idle_timeout
            ]
        for sid in stale:
            try:
                log.info("Reaping idle session %s", sid)
                await self.destroy(sid)
            except Exception:  # noqa: BLE001
                log.exception("Failed to reap session %s", sid)
        return stale

    # ----- lifecycle -----
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
        try:
            login_body = await sess.login_mm()
            if ips:
                await asyncio.gather(*(sess.ensure_md_client(ip) for ip in ips))
        except Exception:
            await sess.close_all()
            raise
        async with self._lock:
            self._sessions[sid] = sess
        self._maybe_start_reaper()
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

    async def describe(self, session_id: str) -> dict[str, Any]:
        sess = await self.get(session_id)
        return sess.describe()

    # ----- show execution with conductor fallback + auto-relogin -----
    async def show_with_mm_then_md_fallback(
        self,
        session_id: str,
        command: str,
        *,
        use_cache: bool,
        cache_tier: CacheTier | None = None,
    ) -> dict[str, Any]:
        sess = await self.get(session_id)
        if not sess.mm_client or not sess.mm_client.has_stored_credentials:
            raise ArubaHttpError("MM session not logged in")
        sess.touch()

        cache_key = (session_id, sess.mm_host, command)
        if use_cache:
            hit = await self.cache.get(cache_key)
            if hit is not None:
                out = dict(hit)
                out["from_cache"] = True
                return out

        ttl = self.cache.ttl_for_tier(cache_tier)

        status, payload = await self._run_show_with_relogin(sess.mm_client, command)
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
            await self.cache.set(cache_key, {**result, "from_cache": False}, ttl_seconds=ttl)
            return result

        mm_skip_msg = (
            "MM rejected the command (conductor restriction); tried configured MDs."
        )
        if not sess.md_ips:
            result["note"] = (
                "No MD list configured, cannot fall back automatically. "
                "Provide md_ips when creating the session, use "
                "aos8.devices.yaml / aos8_session_create_from_config, "
                "or call aos8_show with target='md'."
            )
            result["fallback_attempts"] = []
            await self.cache.set(cache_key, {**result, "from_cache": False}, ttl_seconds=ttl)
            return result

        attempts: list[dict[str, Any]] = []
        for md_ip in sess.md_ips:
            try:
                md_cli = await sess.ensure_md_client(md_ip)
                st, pl = await self._run_show_with_relogin(md_cli, command)
                att = {
                    "md_ip": md_ip,
                    "http_status": st,
                    "still_conductor_msg": _looks_like_not_on_conductor(pl),
                }
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
                    await self.cache.set(
                        ckey_md, {**result_md, "from_cache": False}, ttl_seconds=ttl
                    )
                    return result_md
            except Exception as ex:  # noqa: BLE001
                attempts.append({"md_ip": md_ip, "error": str(ex)})

        result["note"] = "All configured MDs still failed (or still report conductor restriction)."
        result["fallback_attempts"] = attempts
        await self.cache.set(cache_key, {**result, "from_cache": False}, ttl_seconds=ttl)
        return result

    async def show_on_target(
        self,
        session_id: str,
        command: str,
        *,
        target: str,
        md_ip: str | None,
        use_cache: bool,
        cache_tier: CacheTier | None = None,
    ) -> dict[str, Any]:
        sess = await self.get(session_id)
        sess.touch()
        if target == "mm":
            return await self.show_with_mm_then_md_fallback(
                session_id, command, use_cache=use_cache, cache_tier=cache_tier
            )
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
        ttl = self.cache.ttl_for_tier(cache_tier)
        status, payload = await self._run_show_with_relogin(md_cli, command)
        result = _build_tool_result(
            target_host=md_ip.strip(),
            command=command,
            http_status=status,
            raw=payload,
            executed_on="md",
            md_ip_used=md_ip.strip(),
            conductor_rejected=_looks_like_not_on_conductor(payload),
        )
        await self.cache.set(cache_key, {**result, "from_cache": False}, ttl_seconds=ttl)
        return result

    @staticmethod
    async def _run_show_with_relogin(
        client: ArubaDeviceClient, command: str
    ) -> tuple[int, Any]:
        """Login (or refresh by TTL), run ``show``, then optionally logout to free controller slots."""
        await client.ensure_ready_for_show()
        try:
            try:
                return await client.show_command(command)
            except ArubaAuthExpired:
                await client.relogin()
                return await client.show_command(command)
        finally:
            if _LOGOUT_AFTER_EACH_TOOL:
                await client.logout()


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
