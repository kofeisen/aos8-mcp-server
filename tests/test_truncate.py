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


def test_log_truncate_keeps_tail_by_default() -> None:
    r = _log_result(300)
    out = apply_truncation(r, max_lines=10, max_rows=None)
    norm = out["normalized"]
    assert norm["line_count_total"] == 300
    assert len(norm["tail"]) == 10
    assert norm["tail"][-1] == "l299"
    assert norm["head"] == []
    assert len(out["raw"]["lines"]) == 10


def test_log_truncate_keep_head_option() -> None:
    r = _log_result(120)
    out = apply_truncation(r, max_lines=5, max_rows=None, keep_head_for_log=True)
    norm = out["normalized"]
    assert norm["head"] == ["l0", "l1", "l2", "l3", "l4"]
    assert norm["tail"] == []


def test_log_truncate_zero_returns_empty() -> None:
    r = _log_result(50)
    out = apply_truncation(r, max_lines=0, max_rows=None)
    norm = out["normalized"]
    assert norm["head"] == []
    assert norm["tail"] == []
    assert norm["line_count_total"] == 50


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
