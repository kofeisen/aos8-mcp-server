"""Tests for structured log summarization."""

from __future__ import annotations

from aos8_mcp.log_analyze import analyze_log_lines, extract_log_lines
from aos8_mcp.normalize import normalize_payload
from aos8_mcp.syslog_catalog import classify_log_line


def test_extract_log_lines_from_text_format() -> None:
    raw = {"_format": "text", "_raw_text": "line one\nline two\n"}
    assert extract_log_lines(raw) == ["line one", "line two"]


def test_noise_path_lines_are_excluded_from_groups() -> None:
    lines = [
        "@/Users/haoliu/Desktop/123",
        "May 14 20:10:00  authmgr[5362]: Mgmt User Authentication failed. username=admin userip=10.140.3.102",
        "May 14 20:11:00  authmgr[5362]: Mgmt User Authentication failed. username=admin userip=10.140.3.103",
        "@/var/log/messages",
    ]
    out = analyze_log_lines(lines, resource_key="sess:show log security 100")
    summary = out["summary"]
    assert summary["total_lines"] == 4
    assert summary["noise_lines"] == 2
    assert summary["analyzed_lines"] == 2
    assert summary["unique_events"] == 1
    group = summary["error_groups"][0]
    assert group["pattern"] == "Mgmt User Authentication failed"
    assert group["category"] == "Security"
    assert group["process"] == "authmgr"
    assert group["count"] == 2
    assert summary["resource_uri"].startswith("device://logs/")
    assert len(summary["resource_uri"]) > len("device://logs/")


def test_classify_by_error_id_from_catalog() -> None:
    line = (
        "May 16 22:00:00  sapd[148]: <323001> RFD process initialization failed"
    )
    c = classify_log_line(line)
    assert c.error_id == "323001"
    assert c.matched is True
    assert c.category == "System"
    assert "RFD process initialization failed" in c.pattern


def test_groups_multiple_patterns_with_time_range() -> None:
    lines = [
        "May 14 20:10:00  db: Failed to run database query on table users",
        "May 15 08:00:00  db: Failed to run database query timeout",
        "May 16 21:49:45  cli: Error in processing cmd: show ap active",
        "May 16 21:49:53  aaa: USER login successful for admin",
    ]
    out = analyze_log_lines(lines)
    summary = out["summary"]
    assert summary["unique_events"] == 4
    assert summary["time_range"] is not None
    assert "2026-05-14" in summary["time_range"] or "May" not in summary["time_range"]
    patterns = {g["pattern"] for g in summary["error_groups"]}
    assert "Failed to run database query on table users" in patterns or any(
        "Failed to run database query" in p for p in patterns
    )
    assert any("Error in processing cmd" in p for p in patterns)
    assert any("USER login successful" in p for p in patterns)
    assert summary["category_counts"].get("System", 0) >= 2


def test_normalize_log_text_returns_structured_summary() -> None:
    raw = {
        "_format": "text",
        "_raw_text": (
            "May 14 20:10:00  authmgr: Mgmt User Authentication failed. userip=1.2.3.4\n"
            "May 14 20:10:01  authmgr: Mgmt User Authentication failed. userip=5.6.7.8\n"
        ),
    }
    out = normalize_payload("log_text", raw)
    assert out is not None
    assert out["kind"] == "log"
    assert "summary" in out
    assert out["summary"]["error_groups"][0]["count"] == 2
    assert "head" not in out
    assert "tail" not in out
