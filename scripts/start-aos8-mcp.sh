#!/usr/bin/env bash
# 在仓库根目录启动 aos8-mcp-server（Streamable HTTP），便于复制到服务器后直接运行或由 systemd 调用。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${AOS8_MCP_HOST:=0.0.0.0}"
: "${AOS8_MCP_PORT:=8765}"
: "${AOS8_CACHE_TTL_SECONDS:=60}"
# 可选: AOS8_MCP_STATELESS_HTTP=true — Streamable HTTP 无状态模式（见 README「排查 400」）
export AOS8_MCP_HOST AOS8_MCP_PORT AOS8_CACHE_TTL_SECONDS
# 未设置 AOS8_DEVICES_CONFIG 时，默认读取 $ROOT/aos8.devices.yaml（见 aos8_mcp.devices_config）

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  exec "${ROOT}/.venv/bin/python" -m aos8_mcp
fi

if command -v aos8-mcp-server >/dev/null 2>&1; then
  exec aos8-mcp-server
fi

exec python3 -m aos8_mcp
