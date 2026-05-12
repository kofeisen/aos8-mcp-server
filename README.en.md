# aos8-mcp-server

A **read-only** MCP server for **Aruba AOS 8.x**: run `show` commands on Mobility Master (MM) and managed devices (MDs) via the **showcommand** HTTP API. Default transport is **Streamable HTTP**.

> Not an HPE/Aruba official project. You are responsible for credentials, TLS, and network exposure.  
> **中文说明:** [README.md](README.md)

## Device configuration (recommended)

1. `cp aos8.devices.example.yaml aos8.devices.yaml` and fill in MM and each MD `ip` / `username` / `password` (MDs may omit credentials to reuse the MM account).
2. Run the server from a working directory that can read that file, or set `AOS8_DEVICES_CONFIG` to an absolute path.
3. In your MCP client, call **`aos8_session_create_from_config`** (optional `config_path`) so passwords do not appear in chat.

## Features

| Topic | Details |
| --- | --- |
| Session | `aos8_session_create_from_config` / `aos8_session_create` → reuse `session_id` → `aos8_session_destroy`; `aos8_session_status` for health and idle time |
| Execution | MM first; on *not applicable on conductor*, fall back to **configured MD order**; on auth expiry, **one automatic re-login** then retry |
| Tools | Domains: `aos8_controllers`, `aos8_clients`, `aos8_aps`, `aos8_wlan`, `aos8_log`, `aos8_system`, `aos8_network`, `aos8_aaa`, `aos8_cluster`, `aos8_rf`; free-form: `aos8_show`; catalog: `aos8_catalog` |
| Diagnostics | `aos8_ap_diagnose`, `aos8_client_diagnose`, `aos8_health_overview` (parallel `show` chains) |
| Response | `raw` is the parsed device payload; `normalized` is a heuristic summary (tabular output often has `count` + `items`) |
| Truncation | `max_lines` (logs, default last **200** lines), `max_rows` (tables, default **500** rows) |
| Cache | Three tiers: `static` / `near_realtime` / `realtime`; see environment variables below |

## Controller recommendation

Configure **`#no paging`** on MM/MD so `show` output is not stuck in interactive paging (which can break or truncate API results).

## Install

```bash
cd aos8-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # omit .[dev] if you only run the server
```

## Run

**Script (recommended):** switches CWD to the repo root and prefers `.venv/bin/python`.

```bash
chmod +x scripts/start-aos8-mcp.sh
./scripts/start-aos8-mcp.sh
```

**Direct:**

```bash
cd aos8-mcp-server
python -m aos8_mcp
# or
aos8-mcp-server
```

**Common environment variables** (optional; also valid in systemd `Environment=`):

| Variable | Purpose |
| --- | --- |
| `AOS8_MCP_HOST` / `AOS8_MCP_PORT` | Bind address and port (default `0.0.0.0:8765`) |
| `AOS8_DEVICES_CONFIG` | Absolute path to the devices YAML |
| `AOS8_CACHE_TTL_SECONDS` | `near_realtime` tier TTL in seconds (default `15`) |
| `AOS8_CACHE_STATIC_TTL` / `AOS8_CACHE_REALTIME_TTL` | `static` / `realtime` tiers (defaults `120` / `0`; `0` disables cache for that tier) |
| `AOS8_LOG_DEFAULT_TAIL` / `AOS8_TABLE_DEFAULT_CAP` | Default log tail lines and max table rows (`200` / `500`) |
| `AOS8_SESSION_IDLE_TIMEOUT_SECONDS` | Idle auto logout in seconds (default `1800`; `0` disables) |
| `AOS8_SESSION_IDLE_SCAN_SECONDS` | Idle scan interval (default `60`) |
| `AOS8_MCP_STATELESS_HTTP` | `true` for stateless HTTP (some UIs need this) |

**systemd:** adapt `scripts/aos8-mcp.service.example` (`User`, `WorkingDirectory`, `ExecStart`) and install the unit.

## MCP clients

Endpoint: `http://<host>:<port>/mcp` (Streamable HTTP). After `initialize`, responses may include `mcp-session-id`; subsequent requests should send the same header unless `AOS8_MCP_STATELESS_HTTP=true`.

Example (field names depend on your UI):

```json
{
  "mcpServers": {
    "aos8": {
      "url": "http://192.168.1.10:8765/mcp",
      "transport": "streamable-http"
    }
  }
}
```

## Troubleshooting quick reference

| Scenario | Call |
| --- | --- |
| Platform snapshot | `aos8_health_overview(session_id)` |
| AP status / offline | `aos8_ap_diagnose(session_id, ap_name="AP-M020")`; or `aos8_aps` with `variant="database"` and `cli_suffix` using the controller `include` filter on the AP name |
| Client trace | `aos8_client_diagnose(session_id, identifier="aa:bb:cc:dd:ee:ff")` |
| Auth issues | `aos8_aaa` with `variant="state_messages"` and `cli_suffix` using `include` on user or MAC |
| Cluster | `aos8_cluster(..., variant="lc_cluster_group_membership")` |
| Routing | `aos8_network(..., variant="ip_route")` |
| Resources | `aos8_system(..., variant="cpuload")` or `variant="memory"` |
| RF | `aos8_rf(..., variant="arm_rf_summary")` |
| Error log | `aos8_log(..., variant="errorlog", max_lines=100)` |

## Extending and testing

- Preset commands and cache tiers: `aos8_mcp/show_registry.py`; normalization: `aos8_mcp/normalize.py`.
- Tests: `python -m pytest -q` (requires `pip install -e ".[dev]"`).
