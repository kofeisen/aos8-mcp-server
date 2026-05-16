"""Structured summarization for Aruba controller ``show log`` output."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aos8_mcp.syslog_catalog import classify_log_line, group_key

_MONTHS: dict[str, int] = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

_RE_TIMESTAMP = re.compile(
    r"^(\w{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\b"
)
_RE_PATH_LINE = re.compile(r"^@?[/\\][^\s]+$")
_RE_AT_PATH = re.compile(r"@[/\\][^\s]+")
_RE_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_RE_MAC = re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.IGNORECASE)
_RE_NUMBERS = re.compile(r"\b\d+\b")

_MAX_ERROR_GROUPS = 40
_SAMPLE_MAX_LEN = 240


@dataclass
class _GroupAcc:
    pattern: str
    category: str
    severity: str
    error_id: str | None
    process: str | None
    catalog_matched: bool
    count: int = 0
    first_occurrence: str | None = None
    last_occurrence: str | None = None
    sample: str = ""


def extract_log_lines(raw: Any) -> list[str]:
    """Pull non-empty log lines from any raw ``show log`` payload shape."""
    if isinstance(raw, dict) and raw.get("_format") == "log_xml_wrapper":
        lines = raw.get("lines")
        if isinstance(lines, list):
            return [str(ln) for ln in lines if str(ln).strip()]
    if isinstance(raw, dict) and raw.get("_format") == "text":
        text = str(raw.get("_raw_text", ""))
        return [ln for ln in text.splitlines() if ln.strip()]
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list) and v and isinstance(v[0], str):
                return [ln for ln in v if str(ln).strip()]
    if isinstance(raw, str):
        return [ln for ln in raw.splitlines() if ln.strip()]
    return []


def build_resource_uri(resource_key: str) -> str:
    digest = hashlib.sha256(resource_key.encode()).hexdigest()[:12]
    return f"device://logs/{digest}"


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if _RE_PATH_LINE.match(s):
        return True
    if s.startswith("@") and "/" in s and " " not in s:
        return True
    return False


def _parse_timestamp(line: str, *, default_year: int | None = None) -> datetime | None:
    m = _RE_TIMESTAMP.match(line.strip())
    if not m:
        return None
    mon_name, day_s, hh, mm, ss = m.groups()
    month = _MONTHS.get(mon_name)
    if month is None:
        return None
    year = default_year if default_year is not None else datetime.now().year
    try:
        return datetime(
            year, month, int(day_s), int(hh), int(mm), int(ss)
        )
    except ValueError:
        return None


def _format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _normalize_message(line: str) -> str:
    s = line.strip()
    m = _RE_TIMESTAMP.match(s)
    if m:
        s = s[m.end() :].strip()
    s = _RE_AT_PATH.sub("@<path>", s)
    s = _RE_IPV4.sub("<ip>", s)
    s = _RE_MAC.sub("<mac>", s)
    s = _RE_NUMBERS.sub("<n>", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 160:
        s = s[:157] + "..."
    return s or line.strip()[:160]


def _accumulate_group(
    groups: dict[str, _GroupAcc],
    classification: LogClassification,
    *,
    line: str,
    ts_s: str | None,
) -> None:
    key = group_key(classification)
    acc = groups.get(key)
    if acc is None:
        acc = _GroupAcc(
            pattern=classification.pattern,
            category=classification.category,
            severity=classification.severity,
            error_id=classification.error_id,
            process=classification.process,
            catalog_matched=classification.matched,
            sample=line.strip()[:_SAMPLE_MAX_LEN],
        )
        groups[key] = acc
    acc.count += 1
    if classification.matched:
        acc.catalog_matched = True
    if ts_s is not None:
        if acc.first_occurrence is None or ts_s < acc.first_occurrence:
            acc.first_occurrence = ts_s
        if acc.last_occurrence is None or ts_s > acc.last_occurrence:
            acc.last_occurrence = ts_s


def analyze_log_lines(
    lines: list[str],
    *,
    resource_key: str | None = None,
    max_groups: int = _MAX_ERROR_GROUPS,
) -> dict[str, Any]:
    """Return MCP ``normalized`` payload for log tools."""
    year = datetime.now().year
    groups: dict[str, _GroupAcc] = {}
    noise_lines = 0
    parsed_times: list[datetime] = []
    category_counts: dict[str, int] = {}

    for line in lines:
        if _is_noise_line(line):
            noise_lines += 1
            continue
        ts = _parse_timestamp(line, default_year=year)
        ts_s = _format_ts(ts) if ts is not None else None
        if ts is not None:
            parsed_times.append(ts)
        norm = _normalize_message(line)
        classification = classify_log_line(line, normalized=norm)
        category_counts[classification.category] = (
            category_counts.get(classification.category, 0) + 1
        )
        _accumulate_group(groups, classification, line=line, ts_s=ts_s)

    sorted_groups = sorted(groups.values(), key=lambda g: g.count, reverse=True)
    if max_groups > 0:
        sorted_groups = sorted_groups[:max_groups]

    error_groups = [
        {
            "pattern": g.pattern,
            "category": g.category,
            "severity": g.severity,
            "error_id": g.error_id,
            "process": g.process,
            "catalog_matched": g.catalog_matched,
            "count": g.count,
            "first_occurrence": g.first_occurrence,
            "last_occurrence": g.last_occurrence,
            "sample": g.sample,
        }
        for g in sorted_groups
    ]

    time_range: str | None = None
    if parsed_times:
        time_range = f"{_format_ts(min(parsed_times))} ~ {_format_ts(max(parsed_times))}"

    summary: dict[str, Any] = {
        "time_range": time_range,
        "total_lines": len(lines),
        "analyzed_lines": len(lines) - noise_lines,
        "noise_lines": noise_lines,
        "unique_events": len(groups),
        "category_counts": category_counts,
        "error_groups": error_groups,
        "catalog_version": _load_catalog_version(),
    }
    if resource_key:
        summary["resource_uri"] = build_resource_uri(resource_key)

    return {
        "kind": "log",
        "line_count": len(lines),
        "summary": summary,
    }


def _load_catalog_version() -> str:
    try:
        from aos8_mcp.syslog_catalog import _load_catalog_raw

        return str(_load_catalog_raw().get("version", "unknown"))
    except OSError:
        return "unknown"
