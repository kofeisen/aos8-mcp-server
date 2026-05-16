"""Tests for aos8_ap_diagnose composite tool."""

from __future__ import annotations

from typing import Any

import pytest

from aos8_mcp import server


@pytest.mark.asyncio
async def test_ap_diagnose_includes_arm_rf_summary_step_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, Any, str | None]] = []

    async def fake_gather(
        sid: str,
        steps: list[tuple[str, Any, str | None]],
        *,
        md_bias_domains: list[str | None] | None = None,
    ) -> list[dict[str, Any]]:
        captured[:] = steps
        return [
            {"step": label, "ok": True, "normalized": {"count": 1}}
            for label, _, _ in steps
        ]

    monkeypatch.setattr(server, "_gather_steps", fake_gather)

    out = await server.aos8_ap_diagnose(
        session_id="sid-1",
        ap_name="AP-LAB-01",
        include_log_tail=False,
        include_rf=True,
    )
    assert out["ok"] is True
    labels = [row[0] for row in captured]
    assert labels.index("arm_rf_summary") > labels.index("radio_summary")
    arm_row = next(r for r in captured if r[0] == "arm_rf_summary")
    assert arm_row[1].command == "show ap arm rf-summary"
    assert "| include AP-LAB-01" in (arm_row[2] or "")


@pytest.mark.asyncio
async def test_ap_diagnose_include_rf_false_skips_arm_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, Any, str | None]] = []

    async def fake_gather(
        sid: str,
        steps: list[tuple[str, Any, str | None]],
        *,
        md_bias_domains: list[str | None] | None = None,
    ) -> list[dict[str, Any]]:
        captured[:] = steps
        return [
            {"step": label, "ok": True, "normalized": {"count": 1}}
            for label, _, _ in steps
        ]

    monkeypatch.setattr(server, "_gather_steps", fake_gather)

    await server.aos8_ap_diagnose(
        session_id="sid-1",
        ap_name="AP-LAB-01",
        include_log_tail=False,
        include_rf=False,
    )
    labels = [row[0] for row in captured]
    assert "arm_rf_summary" not in labels
