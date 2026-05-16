"""Tests for on-disk log summary persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aos8_mcp import log_store
from aos8_mcp.log_analyze import analyze_log_lines


def test_disabled_by_default() -> None:
    assert log_store.log_summary_dir() is None
    path = log_store.persist_log_summary(
        session_id="s",
        command="show log all",
        normalized={"kind": "log", "summary": {}},
    )
    assert path is None


@pytest.fixture()
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AOS8_LOG_SUMMARY_DIR", str(tmp_path))
    return tmp_path


def test_persist_writes_json_file(log_dir: Path) -> None:
    norm = analyze_log_lines(
        [
            "May 14 20:10:00  authmgr: Mgmt User Authentication failed. userip=1.2.3.4",
        ],
        resource_key="sid:show log errorlog 10",
    )
    path = log_store.persist_log_summary(
        session_id="sid-abc",
        command="show log errorlog 10",
        normalized=norm,
        variant="errorlog",
        target_host="10.0.0.1",
    )
    assert path is not None
    written = Path(path)
    assert written.is_file()
    assert written.parent == log_dir
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["session_id"] == "sid-abc"
    assert data["command"] == "show log errorlog 10"
    assert data["normalized"]["summary"]["error_groups"][0]["count"] == 1


def test_disabled_when_env_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AOS8_LOG_SUMMARY_DIR", "")
    assert log_store.log_summary_dir() is None
    assert list(tmp_path.glob("*.json")) == []
