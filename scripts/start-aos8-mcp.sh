#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${AOS8_MCP_HOST:=0.0.0.0}"
: "${AOS8_MCP_PORT:=8765}"
: "${AOS8_CACHE_TTL_SECONDS:=60}"

export AOS8_MCP_HOST AOS8_MCP_PORT AOS8_CACHE_TTL_SECONDS
# When AOS8_DEVICES_CONFIG is not set, default to reading $ROOT/aos8.devices.yaml (see aos8_mcp.devices_config)

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  exec "${ROOT}/.venv/bin/python" -m aos8_mcp
fi

if command -v aos8-mcp-server >/dev/null 2>&1; then
  exec aos8-mcp-server
fi

exec python3 -m aos8_mcp
