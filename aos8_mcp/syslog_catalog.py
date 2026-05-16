"""ArubaOS syslog catalog loader and line classifier (Reference Guide–based)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

_RE_ERROR_ID = re.compile(r"<(\d{6})>")
_RE_TIMESTAMP = re.compile(r"^(\w{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\b")
_RE_PROCESS = re.compile(r"^(\w+)(?:\[\d+\])?:\s*", re.IGNORECASE)
_RE_PLACEHOLDER = re.compile(r"\[[^\]]+\]")
_RE_KV_FIELD = re.compile(r"\b\w+=[^\s]+")
_MIN_TEXT_KEY_LEN = 12

_SEVERITY_KEYWORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bemerg(ency)?\b", re.I), "Emergency"),
    (re.compile(r"\balert\b", re.I), "Alert"),
    (re.compile(r"\bcritical\b", re.I), "Critical"),
    (re.compile(r"\berror\b", re.I), "Error"),
    (re.compile(r"\bfailed\b", re.I), "Error"),
    (re.compile(r"\bwarn(ing)?\b", re.I), "Warning"),
    (re.compile(r"\bnotice\b", re.I), "Notice"),
    (re.compile(r"\binfo(rmation(al)?)?\b", re.I), "Information"),
    (re.compile(r"\bdebug\b", re.I), "Debug"),
)


@dataclass(frozen=True)
class LogClassification:
    pattern: str
    category: str
    severity: str
    error_id: str | None
    process: str | None
    matched: bool  # True when matched a catalog entry by id or message text


def _catalog_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "syslog_catalog.json"


@lru_cache(maxsize=1)
def _load_catalog_raw() -> dict[str, Any]:
    path = _catalog_path()
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    ref = resources.files("aos8_mcp").joinpath("data/syslog_catalog.json")
    return json.loads(ref.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _compiled_catalog() -> tuple[
    dict[str, dict[str, str]],
    list[tuple[str, dict[str, str]]],
    dict[str, list[str]],
]:
    raw = _load_catalog_raw()
    by_id: dict[str, dict[str, str]] = raw.get("by_id") or {}
    text_index: list[tuple[str, dict[str, str]]] = []
    for item in raw.get("text_index") or []:
        key = item.get("key") or ""
        if not key:
            continue
        text_index.append(
            (
                key,
                {
                    "error_id": item.get("error_id") or "",
                    "category": item.get("category") or "System",
                    "severity": item.get("severity") or "Error",
                    "message": item.get("message") or "",
                },
            )
        )
    process_categories: dict[str, list[str]] = raw.get("process_categories") or {}
    return by_id, text_index, process_categories


def _message_key(message: str) -> str:
    s = _RE_PLACEHOLDER.sub("", message)
    s = _RE_KV_FIELD.sub("", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _strip_timestamp(line: str) -> str:
    s = line.strip()
    m = _RE_TIMESTAMP.match(s)
    if m:
        return s[m.end() :].strip()
    return s


def extract_process_and_body(line: str) -> tuple[str | None, str]:
    """Return ``(process, message_body)`` after the syslog timestamp."""
    rest = _strip_timestamp(line)
    m = _RE_PROCESS.match(rest)
    if m:
        return m.group(1).lower(), rest[m.end() :].strip()
    if ":" in rest:
        proc, _, body = rest.partition(":")
        if proc.isidentifier() and len(proc) <= 32:
            return proc.lower(), body.strip()
    return None, rest


def _infer_severity(text: str) -> str:
    for pat, label in _SEVERITY_KEYWORDS:
        if pat.search(text):
            return label
    return "Notice"


def _category_from_process(process: str | None, process_categories: dict[str, list[str]]) -> str:
    if not process:
        return "System"
    cats = process_categories.get(process)
    if not cats:
        return "System"
    return cats[0].title()


def _lookup_by_message(body_key: str, text_index: list[tuple[str, dict[str, str]]]) -> dict[str, str] | None:
    """Longest prefix match on normalized message body (avoids ``username=`` false positives)."""
    for key, entry in text_index:
        if len(key) < _MIN_TEXT_KEY_LEN:
            continue
        if body_key.startswith(key):
            return entry
    return None


def _canonical_pattern(message: str, body: str) -> str:
    msg = message.strip() or body.strip()
    if not message.strip():
        head, sep, _tail = msg.partition(".")
        if sep and len(head.strip()) >= 8:
            msg = head.strip()
        msg = _RE_KV_FIELD.sub("", msg)
    msg = _RE_PLACEHOLDER.sub("", msg)
    msg = re.sub(r"\s+", " ", msg).strip(" .")
    if len(msg) <= 120:
        return msg
    return msg[:117] + "..."


def classify_log_line(line: str, *, normalized: str | None = None) -> LogClassification:
    """Classify one ``show log`` line using the syslog reference catalog."""
    by_id, text_index, process_categories = _compiled_catalog()
    process, body = extract_process_and_body(line)
    _ = normalized  # reserved; matching uses the raw message body only
    body_key = _message_key(body)

    m = _RE_ERROR_ID.search(line)
    if m:
        entry = by_id.get(m.group(1))
        if entry:
            return LogClassification(
                pattern=_canonical_pattern(entry.get("message", ""), body),
                category=entry.get("category") or "System",
                severity=entry.get("severity") or "Error",
                error_id=m.group(1),
                process=process,
                matched=True,
            )

    entry = _lookup_by_message(body_key, text_index)
    if entry:
        return LogClassification(
            pattern=_canonical_pattern(entry.get("message", ""), body),
            category=entry.get("category") or "System",
            severity=entry.get("severity") or "Error",
            error_id=entry.get("error_id") or None,
            process=process,
            matched=True,
        )

    category = _category_from_process(process, process_categories)
    severity = _infer_severity(body)
    pattern = _canonical_pattern("", body)
    if len(pattern) <= 3:
        pattern = body[:120] if body else line.strip()[:120]
    return LogClassification(
        pattern=pattern,
        category=category,
        severity=severity,
        error_id=None,
        process=process,
        matched=False,
    )


def group_key(classification: LogClassification) -> str:
    """Stable aggregation key for ``error_groups``."""
    parts = [classification.category, classification.severity, classification.pattern]
    if classification.error_id:
        parts.insert(0, classification.error_id)
    return " | ".join(parts)
