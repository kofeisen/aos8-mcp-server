"""HTTP client for AOS8 MM/MD login, logout, and showcommand API.

The client owns its own cookie jar and login tokens. Credentials are kept
locally (in-process only) so an authenticated connection can re-login itself
when the controller expires the session.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx


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


def _looks_like_auth_failure(status: int, payload: Any) -> bool:
    if status in _AUTH_HTTP_STATUSES:
        return True
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
        self._username: str | None = None
        self._password: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def is_authenticated(self) -> bool:
        return self.tokens is not None

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
        self._username = username
        self._password = password
        return body

    async def relogin(self) -> None:
        """Re-establish the session using the credentials supplied to ``login``."""
        if self._username is None or self._password is None:
            raise ArubaHttpError("Cannot re-login: credentials were never supplied")
        self.tokens = None
        await self.login(self._username, self._password)

    async def logout(self) -> None:
        if not self.tokens:
            return
        url = f"{self.base_url}/v1/api/logout"
        try:
            await self._client.get(
                url,
                headers={"X-CSRF-Token": self.tokens.csrf},
            )
        except httpx.HTTPError:
            pass
        self.tokens = None

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
