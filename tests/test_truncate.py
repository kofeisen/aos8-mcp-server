"""Tests for the apply_truncation post-processor."""

from __future__ import annotations

from aos8_mcp.normalize import normalize_payload
from aos8_mcp.truncate import apply_truncation


def _log_result(n: int) -> dict:
    raw = {"_format": "log_xml_wrapper", "lines": [f"l{i}" for i in range(n)]}
    return {"raw": raw, "normalized": normalize_payload("log_text", raw)}


def test_no_op_when_both_caps_are_none() -> None:
    r = _log_result(50)
    out = apply_truncation(r, max_lines=None, max_rows=None)
    assert out is r


def test_log_truncate_keeps_tail_in_raw_only() -> None:
    r = _log_result(300)
    out = apply_truncation(r, max_lines=10, max_rows=None)
    norm = out["normalized"]
    assert norm["line_count_total"] == 300
    assert norm["summary"]["total_lines"] == 300
    assert norm["summary"]["raw_lines_kept"] == 10
    assert len(out["raw"]["lines"]) == 10
    assert out["raw"]["lines"][-1] == "l299"


def test_log_truncate_keep_head_option() -> None:
    r = _log_result(120)
    out = apply_truncation(r, max_lines=5, max_rows=None, keep_head_for_log=True)
    norm = out["normalized"]
    assert norm["summary"]["raw_lines_kept"] == 5
    assert out["raw"]["lines"][0] == "l0"


def test_log_truncate_zero_clears_raw() -> None:
    r = _log_result(50)
    out = apply_truncation(r, max_lines=0, max_rows=None)
    norm = out["normalized"]
    assert norm["summary"]["raw_lines_kept"] == 0
    assert norm["line_count_total"] == 50
    assert out["raw"]["lines"] == []


def test_table_truncate_preserves_count_total() -> None:
    raw = {"AP Database": [{"i": i} for i in range(2000)]}
    norm = normalize_payload("ap_database", raw)
    out = apply_truncation({"raw": raw, "normalized": norm}, max_lines=None, max_rows=100)
    assert out["normalized"]["count_total"] == 2000
    assert len(out["normalized"]["items"]) == 100
    assert out["normalized"].get("truncated") is True


def test_table_truncate_no_op_when_under_cap() -> None:
    raw = {"AP Database": [{"i": i} for i in range(10)]}
    norm = normalize_payload("ap_database", raw)
    out = apply_truncation({"raw": raw, "normalized": norm}, max_lines=None, max_rows=100)
    assert out["normalized"]["count_total"] == 10
    assert "truncated" not in out["normalized"]
    assert len(out["normalized"]["items"]) == 10


def test_table_truncate_zero_yields_empty_items() -> None:
    raw = {"AP Database": [{"i": i} for i in range(5)]}
    norm = normalize_payload("ap_database", raw)
    out = apply_truncation({"raw": raw, "normalized": norm}, max_lines=None, max_rows=0)
    assert out["normalized"]["items"] == []
    assert out["normalized"]["count_total"] == 5
