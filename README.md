# aos8-mcp-server

面向 **Aruba AOS 8.x** 的 **只读** MCP 服务：通过 Mobility Master（MM）与 MD 上的 **showcommand** HTTP API 执行 `show`，默认 **Streamable HTTP**。

> 非 HPE 官方项目；凭据与网络访问由部署方自行负责。  
> **English:** [README.en.md](README.en.md)

## 设备配置（推荐）

1. `cp aos8.devices.example.yaml aos8.devices.yaml`，填写 MM 与 `md` 列表的 `ip` / `username` / `password`（MD 可省略账号则沿用 MM）。
2. 进程工作目录需能读到该文件，或设置 `AOS8_DEVICES_CONFIG` 指向绝对路径。
3. 在客户端中调用 **`aos8_session_create_from_config`** 建立会话（可选 `config_path`），避免在对话里粘贴密码。

## 功能要点

| 项 | 说明 |
| --- | --- |
| 会话 | `aos8_session_create_from_config` / `aos8_session_create` → 复用 `session_id` → `aos8_session_destroy`；`aos8_session_status` 查看状态与空闲时间 |
| 执行 | MM 优先；若提示 *not applicable on conductor*，按配置 **MD 顺序** 回落；Token 失效时 **自动重登一次** |
| 工具 | 领域：`aos8_controllers`、`aos8_clients`、`aos8_aps`、`aos8_wlan`、`aos8_log`、`aos8_system`、`aos8_network`、`aos8_aaa`、`aos8_cluster`、`aos8_rf`、`aos8_datapath`；自由：`aos8_show`；目录：`aos8_catalog` |
| 诊断 | `aos8_ap_diagnose`、`aos8_client_diagnose`、`aos8_health_overview`、`aos8_forwarding_overview`（内部并行多条 `show`） |
| 响应 | `raw` 为设备原始解析结果；`normalized` 为启发式摘要（表格类常见 `count` + `items`） |
| 裁剪 | `max_lines`（日志，默认保留尾部 200 行）、`max_rows`（表格，默认 500 行） |
| 缓存 | `static` / `near_realtime` / `realtime` 三档 TTL，见下方环境变量 |

## 控制器侧建议

在 MM/MD 上配置 **`#no paging`**，避免 `show` 分页导致 API 输出异常或截断。

## 安装

```bash
cd aos8-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # 仅运行服务可省略 .[dev]
```

## 启动

**脚本（推荐）：** 将工作目录切到仓库根目录，优先使用 `.venv/bin/python`。

```bash
chmod +x scripts/start-aos8-mcp.sh
./scripts/start-aos8-mcp.sh
```

**直接运行：**

```bash
cd aos8-mcp-server
python -m aos8_mcp
# 或
aos8-mcp-server
```

**常用环境变量**（可选；亦可在 systemd `Environment=` 中设置）：

| 变量 | 含义 |
| --- | --- |
| `AOS8_MCP_HOST` / `AOS8_MCP_PORT` | 监听地址与端口（默认 `0.0.0.0:8765`） |
| `AOS8_DEVICES_CONFIG` | 设备 YAML 绝对路径 |
| `AOS8_CACHE_TTL_SECONDS` | `near_realtime` 档 TTL（秒，默认 `15`） |
| `AOS8_CACHE_STATIC_TTL` / `AOS8_CACHE_REALTIME_TTL` | `static` / `realtime` 档（默认 `120` / `0`，`0` 表示不缓存） |
| `AOS8_LOG_DEFAULT_TAIL` / `AOS8_TABLE_DEFAULT_CAP` | 日志尾部行数、表格最大行数（默认 `200` / `500`） |
| `AOS8_SESSION_IDLE_TIMEOUT_SECONDS` | 空闲自动登出（秒，默认 `1800`；`0` 关闭） |
| `AOS8_SESSION_IDLE_SCAN_SECONDS` | 空闲扫描间隔（默认 `60`） |
| `AOS8_MCP_STATELESS_HTTP` | `true` 时每请求无状态，部分 Web UI 握手更简单 |

**systemd：** 参考 `scripts/aos8-mcp.service.example` 修改 `User`、`WorkingDirectory`、`ExecStart` 后安装单元。

## MCP 客户端

端点：`http://<主机>:<端口>/mcp`（Streamable HTTP）。`initialize` 后响应头含 `mcp-session-id`，后续请求需带同名头（除非开启 `AOS8_MCP_STATELESS_HTTP`）。

示例（字段以你所用 UI 文档为准）：

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

## 排障速查

| 场景 | 调用 |
| --- | --- |
| 平台总览 | `aos8_health_overview(session_id)` |
| AP 状态 / 离线 | `aos8_ap_diagnose(session_id, ap_name="AP-M020")`；或 `aos8_aps` + `variant="database"` + `cli_suffix` 使用控制器上的 `include` 过滤 AP 名 |
| 终端 | `aos8_client_diagnose(session_id, identifier="aa:bb:cc:dd:ee:ff")` |
| 认证 | `aos8_aaa` + `variant="state_messages"` + `cli_suffix` 用 `include` 过滤用户或 MAC |
| 集群 | `aos8_cluster(..., variant="lc_cluster_group_membership")`；自动落到 MD（如需指定成员加 `md_ip="10.1.1.1"`）。常用变体：`heartbeat_counters`、`load_ap`、`history`、`vlan_probe_status`、`dp_cluster_details` + `arg="peer 10.1.1.1"` |
| 路由 | `aos8_network(..., variant="ip_route")` |
| 资源 | `aos8_system(..., variant="cpuload")` 或 `variant="memory"` |
| RF | `aos8_rf(..., variant="arm_rf_summary")` |
| 错误日志 | `aos8_log(..., variant="errorlog", max_lines=100)` |
| 转发面快照 | `aos8_forwarding_overview(session_id)`；可选 `ap_name` 过滤该 AP 的隧道 |
| 转发排错 | `aos8_datapath(..., variant="tunnel")`、`variant="bridge"` + `ap_name="AP-M020"`、`variant="session_table"` + `arg="10.1.1.1"`、`variant="tunnel_id"` + `arg="12 trusted-vlan"` |

## 扩展与测试

- 预设命令与缓存档位：`aos8_mcp/show_registry.py`；归一化：`aos8_mcp/normalize.py`。
- 运行测试：`python -m pytest -q`（需 `pip install -e ".[dev]"`）。
