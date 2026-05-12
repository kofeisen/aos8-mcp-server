"""Server-side post-processing to keep responses LLM-friendly.

Two knobs are supported by tools:

* ``max_lines``  — apply to log-style payloads (keeps the tail by default
  because operators almost always want the most recent entries).
* ``max_rows``   — apply to table-style payloads after normalization.

In both cases the original ``count`` / total length is preserved under
``*_total`` so the model can still reason about the full size.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def apply_truncation(
    result: dict[str, Any],
    *,
    max_lines: int | None,
    max_rows: int | None,
    keep_head_for_log: bool = False,
) -> dict[str, Any]:
    """Return a shallow copy of ``result`` with truncated ``raw`` / ``normalized``.

    ``result`` is the tool dict already containing ``raw`` and ``normalized``.
    """
    if max_lines is None and max_rows is None:
        return result

    out = dict(result)
    norm = out.get("normalized")
    raw = out.get("raw")

    if max_lines is not None and isinstance(norm, dict) and norm.get("kind") == "log":
        full_lines = _full_log_lines(raw)
        out["normalized"] = _truncate_log_normalized(
            norm, max_lines, keep_head_for_log, full_lines
        )
        if isinstance(raw, dict):
            out["raw"] = _truncate_log_raw(raw, max_lines, keep_head_for_log)

    if max_rows is not None and isinstance(norm, dict) and "items" in norm:
        out["normalized"] = _truncate_table_normalized(norm, max_rows)

    return out


def _full_log_lines(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return []
    lines = raw.get("lines")
    if isinstance(lines, list):
        return list(lines)
    text = raw.get("_raw_text")
    if isinstance(text, str) and text:
        return [ln for ln in text.splitlines() if ln.strip()]
    return []


def _truncate_log_normalized(
    norm: dict[str, Any],
    max_lines: int,
    keep_head: bool,
    full_lines: list[str],
) -> dict[str, Any]:
    n = int(norm.get("line_count") or len(full_lines))
    truncated = dict(norm)
    truncated["line_count_total"] = n
    if max_lines <= 0 or not full_lines:
        truncated["head"] = []
        truncated["tail"] = []
        return truncated
    if keep_head:
        truncated["head"] = full_lines[:max_lines]
        truncated["tail"] = []
    else:
        # Default to keeping the tail N lines in operational scenarios.
        truncated["tail"] = full_lines[-max_lines:]
        truncated["head"] = []
    return truncated


def _truncate_log_raw(raw: dict[str, Any], max_lines: int, keep_head: bool) -> dict[str, Any]:
    out = deepcopy(raw)
    lines = out.get("lines")
    if isinstance(lines, list):
        out["line_count_total"] = len(lines)
        if max_lines > 0:
            out["lines"] = lines[:max_lines] if keep_head else lines[-max_lines:]
        else:
            out["lines"] = []
    text = out.get("_raw_text")
    if isinstance(text, str) and text:
        all_lines = text.splitlines()
        out["line_count_total"] = len(all_lines)
        if max_lines > 0:
            kept = all_lines[:max_lines] if keep_head else all_lines[-max_lines:]
        else:
            kept = []
        out["_raw_text"] = "\n".join(kept)
    return out


def _truncate_table_normalized(norm: dict[str, Any], max_rows: int) -> dict[str, Any]:
    items = norm.get("items")
    if not isinstance(items, list):
        return norm
    total = len(items)
    out = dict(norm)
    out["count_total"] = total
    if max_rows <= 0:
        out["items"] = []
    elif total > max_rows:
        out["items"] = items[:max_rows]
        out["truncated"] = True
    return out
