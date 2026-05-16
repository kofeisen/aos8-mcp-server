"""HTTP client for AOS8 MM/MD login and showcommand API.

The client owns its own cookie jar and login tokens. Credentials are kept
locally (in-process only) so an authenticated connection can re-login itself
when the controller expires the session.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


def _uidaruba_ttl_seconds() -> float:
    """API session cookie lifetime (Aruba commonly ~15 minutes). Overridable for labs."""
    return float(os.environ.get("AOS8_UIDARUBA_TTL_SECONDS", "900"))


def configured_uidaruba_ttl_seconds() -> float:
    """Same value used for proactive token refresh before ``show_command``."""
    return _uidaruba_ttl_seconds()


def _uidaruba_refresh_skew_seconds() -> float:
    """Re-login this many seconds *before* the TTL window ends."""
    return float(os.environ.get("AOS8_UIDARUBA_REFRESH_SKEW_SECONDS", "30"))


NOT_ON_CONDUCTOR_MARKERS = (
    "This command is not applicable on conductor switch",
    "This command is not applicable on conductor",
)

# Body fragments / HTTP statuses that signal an expired or rejected token.
_AUTH_HTTP_STATUSES = {401, 403}
_AUTH_BODY_MARKERS = (
    "you must authenticate yourself",
    "authentication failed",
    "session expired",
    "not authorized",
    "csrf",
)


@dataclass
class LoginTokens:
    uidaruba: str
    csrf: str


class ArubaHttpError(RuntimeError):
    pass


class ArubaAuthExpired(ArubaHttpError):
    """Raised when the controller indicates the cached tokens are no longer valid."""


def _base_url(host: str) -> str:
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    return f"https://{host}:4343"


def _looks_like_not_on_conductor(payload: Any) -> bool:
    blob = payload
    if not isinstance(blob, str):
        try:
            blob = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            blob = str(payload)
    lower = blob.lower()
    return any(m.lower() in lower for m in NOT_ON_CONDUCTOR_MARKERS)


def _is_log_show_payload(payload: Any) -> bool:
    """``show log`` bodies often mention auth failures; do not treat those as API auth errors."""
    if not isinstance(payload, dict):
        return False
    fmt = payload.get("_format")
    if fmt == "log_xml_wrapper":
        return True
    if fmt == "text":
        raw = str(payload.get("_raw_text", ""))
        if "<my_xml_tag" in raw.lower():
            return True
        # Multi-line text is almost always log output, not an API error page.
        if raw.count("\n") >= 3:
            return True
    return False


def _looks_like_auth_failure(status: int, payload: Any) -> bool:
    if status in _AUTH_HTTP_STATUSES:
        return True
    if _is_log_show_payload(payload):
        return False
    if isinstance(payload, dict):
        gr = payload.get("_global_result")
        if isinstance(gr, dict):
            return str(gr.get("status", "0")) != "0"
    blob = payload
    if not isinstance(blob, str):
        try:
            blob = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            blob = str(payload)
    lower = blob.lower()
    return any(m in lower for m in _AUTH_BODY_MARKERS)


class ArubaDeviceClient:
    """One logical device (MM or MD IP) — owns cookie jar and tokens."""

    def __init__(self, host: str, verify_ssl: bool) -> None:
        self.host = host
        self.base_url = _base_url(host)
        self.verify_ssl = verify_ssl
        self._client = httpx.AsyncClient(
            verify=verify_ssl,
            timeout=httpx.Timeout(120.0, connect=30.0),
            limits=httpx.Limits(max_connections=10),
            follow_redirects=True,
        )
        self.tokens: LoginTokens | None = None
        self._token_obtained_at: float | None = None
        self._username: str | None = None
        self._password: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def is_authenticated(self) -> bool:
        return self.tokens is not None

    @property
    def has_stored_credentials(self) -> bool:
        """True after a successful ``login`` (tokens may be cleared on TTL refresh)."""
        return self._username is not None and self._password is not None

    async def login(self, username: str, password: str) -> dict[str, Any]:
        url = f"{self.base_url}/v1/api/login"
        resp = await self._client.post(
            url,
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = _safe_json(resp)
        gr = body.get("_global_result") if isinstance(body, dict) else None
        if not isinstance(gr, dict) or str(gr.get("status", "1")) != "0":
            msg = gr.get("status_str", resp.text) if isinstance(gr, dict) else resp.text
            raise ArubaHttpError(f"Login failed ({resp.status_code}): {msg}")
        uid = gr.get("UIDARUBA")
        csrf = gr.get("X-CSRF-Token")
        if not uid or not csrf:
            raise ArubaHttpError("Login response missing UIDARUBA or X-CSRF-Token")
        self.tokens = LoginTokens(uidaruba=str(uid), csrf=str(csrf))
        self._token_obtained_at = time.monotonic()
        self._username = username
        self._password = password
        return body

    async def relogin(self) -> None:
        """Re-establish the session using the credentials supplied to ``login``."""
        if self._username is None or self._password is None:
            raise ArubaHttpError("Cannot re-login: credentials were never supplied")
        self.tokens = None
        self._token_obtained_at = None
        await self.login(self._username, self._password)

    def _token_ttl_expired(self) -> bool:
        if self.tokens is None or self._token_obtained_at is None:
            return False
        ttl = _uidaruba_ttl_seconds()
        skew = _uidaruba_refresh_skew_seconds()
        if ttl <= 0:
            return False
        return (time.monotonic() - self._token_obtained_at) > max(0.0, ttl - skew)

    async def ensure_ready_for_show(self) -> None:
        """Ensure valid UIDARUBA/X-CSRF-Token before ``show_command`` (login / relogin / TTL refresh)."""
        if self._username is None or self._password is None:
            raise ArubaHttpError("Not logged in; call login first")
        if not self.tokens:
            await self.relogin()
        elif self._token_ttl_expired():
            await self.relogin()

    async def show_command(self, command: str) -> tuple[int, Any]:
        """Execute one ``show`` call. Raises ``ArubaAuthExpired`` for stale tokens."""
        if not self.tokens:
            raise ArubaHttpError("Not logged in; call login first")
        url = f"{self.base_url}/v1/configuration/showcommand"
        resp = await self._client.get(
            url,
            params={"command": command, "UIDARUBA": self.tokens.uidaruba},
            headers={"X-CSRF-Token": self.tokens.csrf},
        )
        parsed = _parse_show_body(resp.text)
        if _looks_like_auth_failure(resp.status_code, parsed):
            raise ArubaAuthExpired(
                f"Auth rejected (HTTP {resp.status_code}); credentials may have expired"
            )
        return resp.status_code, parsed


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {"_raw_text": resp.text}


def _parse_show_body(text: str) -> Any:
    text = text.strip()
    if not text:
        return {"_empty": True}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # show log all: pseudo-XML wrapper + plain lines
    m = re.search(r"<my_xml_tag[^>]*>(.*?)</my_xml_tag[^>]*>", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        inner = m.group(1).strip()
        lines = [ln for ln in inner.splitlines() if ln.strip()]
        return {"_format": "log_xml_wrapper", "lines": lines, "_raw_text": text}
    return {"_format": "text", "_raw_text": text}
