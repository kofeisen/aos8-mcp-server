"""Optional on-disk persistence for structured log summaries (disabled by default)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_SEGMENT = re.compile(r"[^a-zA-Z0-9._-]+")


def log_summary_dir() -> Path | None:
    """Return output directory only when ``AOS8_LOG_SUMMARY_DIR`` is set to a non-empty path."""
    raw = os.environ.get("AOS8_LOG_SUMMARY_DIR")
    if raw is None:
        return None
    s = raw.strip()
    if not s or s.lower() in ("0", "false", "no", "off", "disable", "disabled"):
        return None
    return Path(s).expanduser().resolve()


def _safe_name(part: str, *, max_len: int = 48) -> str:
    s = _SAFE_SEGMENT.sub("_", part.strip()).strip("_")
    return (s[:max_len] if s else "unknown")


def persist_log_summary(
    *,
    session_id: str,
    command: str,
    normalized: dict[str, Any],
    variant: str | None = None,
    target_host: str | None = None,
    executed_on: str | None = None,
    md_ip_used: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Write one JSON record when persistence is enabled; otherwise no-op."""
    out_dir = log_summary_dir()
    if out_dir is None:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)

    summary = normalized.get("summary") if isinstance(normalized, dict) else {}
    resource = ""
    if isinstance(summary, dict):
        resource = str(summary.get("resource_uri") or "")
    resource_id = resource.rsplit("/", 1)[-1] if resource else "noid"

    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%S")
    host_part = _safe_name(target_host or "unknown", max_len=24)
    variant_part = _safe_name(variant or "log")
    filename = f"{stamp}_{host_part}_{resource_id}_{variant_part}.json"
    path = out_dir / filename

    record: dict[str, Any] = {
        "recorded_at": ts.isoformat(),
        "session_id": session_id,
        "command": command,
        "variant": variant,
        "target_host": target_host,
        "executed_on": executed_on,
        "md_ip_used": md_ip_used,
        "normalized": normalized,
    }
    if extra:
        record["meta"] = extra

    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(path)
