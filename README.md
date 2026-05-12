# aos8-mcp-server

面向 **Aruba AOS 8.x**（以 8.10 为主）的 **只读** MCP 服务：通过 Mobility Master（MM）及部分 MD 上的 **showcommand** HTTP API 暴露常用 `show`，默认 **Streamable HTTP**，便于开源 Chat UI / DeepSeek 等客户端对接。

> 非 HPE 官方项目；凭据与网络访问风险由部署方自行评估。

## 设备与凭据文件（推荐）

1. 复制模板：`cp aos8.devices.example.yaml aos8.devices.yaml`
2. 编辑 `aos8.devices.yaml`，填写 MM 的 `ip` / `username` / `password`，以及 `md` 列表（每台 `ip`；若与 MM 账号不同可单独写 `username` / `password`）。
3. 启动 MCP 进程时，**工作目录**需能访问该文件；或通过环境变量指定路径：  
   `export AOS8_DEVICES_CONFIG=/绝对路径/aos8.devices.yaml`
4. Chat 里调用 **`aos8_session_create_from_config`**（可选 `config_path`）即可建立会话，无需在对话中粘贴密码。

`aos8.devices.yaml` 已列入 `.gitignore`，避免误提交。

## 功能概要

- **会话生命周期**：`aos8_session_create_from_config`（读本地 YAML，推荐）或 `aos8_session_create`（参数传入）登录 MM → 多次工具调用复用 `session_id` → `aos8_session_destroy` 注销并清缓存；新增 `aos8_session_status` 自检会话健康。
- **执行策略**：默认在 **MM** 上执行；若响应中含 *This command is not applicable on conductor switch*，则按配置中 **MD 顺序** 自动回落。Token 过期时**自动重登一次**再重试。
- **领域工具**（统一为 `variant + cli_suffix + command_override + use_cache + max_*` 的形态）：
  - `aos8_controllers` / `aos8_clients` / `aos8_aps` / `aos8_wlan` / `aos8_log`
  - `aos8_system`（version / license / cpuload / memory / storage / inventory / uptime / image_version …）
  - `aos8_network`（vlan / port_status / ip_interface_brief / ip_route / ospf / arp / dhcp …）
  - `aos8_aaa`（authentication-server all / server-group / state messages / 各类 profile …）
  - `aos8_cluster`（lc-cluster group-membership / switches state / heartbeat / master-redundancy …）
  - `aos8_rf`（arm rf-summary / monitor stats / bss-table / radio-summary …）
- **组合诊断**：`aos8_ap_diagnose(ap_name)`、`aos8_client_diagnose(identifier)`、`aos8_health_overview()`，并行串好一组 show 并返回结构化要点。
- **统一目录**：`aos8_catalog(domain=...)` 一次列出所有 domain/variant 与默认命令（取代旧的 `aos8_ap_show_variants` / `aos8_wlan_show_variants`）。
- **响应**：始终包含 **`raw`**（设备返回解析结果）与 **`normalized`**（启发式摘要，常见表格类返回 `count + items`）。
- **服务端裁剪**：`max_lines`（log 类，默认尾部 200 行）与 `max_rows`（表格类，默认 500 行）按需生效，AI 拿到的上下文不会被一条 `show log all` 灌爆。
- **缓存分档**：`static`（默认 120s）/ `near_realtime`（默认 15s）/ `realtime`（默认 0s，不缓存）。各 variant 自带 tier，整体 TTL 可用环境变量调整。

## 建议的 MM 配置

在 MM/MD 上配置 **`#no paging`**，避免 `show` 进入交互分页；若未关闭，API 行为可能异常或截断，请在控制器侧自行处理。

## 安装（内网）

```bash
cd aos8-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 启动服务

### 方式一：启动脚本（推荐，便于拷到服务器）

脚本会将**工作目录**切到仓库根目录，从而默认找到根目录下的 `aos8.devices.yaml`；并优先使用 `.venv/bin/python`。

```bash
chmod +x scripts/start-aos8-mcp.sh

# 可选环境变量（脚本内已有默认值，也可在 systemd 里写 Environment=）
export AOS8_MCP_HOST=0.0.0.0
export AOS8_MCP_PORT=8765
export AOS8_CACHE_TTL_SECONDS=15           # near_realtime 档默认 TTL（兼容旧名）
export AOS8_CACHE_STATIC_TTL=120           # static 档（version / license 等）
export AOS8_CACHE_REALTIME_TTL=0           # realtime 档（log / cpuload 等不缓存）
export AOS8_LOG_DEFAULT_TAIL=200           # 大日志默认保留尾部行数
export AOS8_TABLE_DEFAULT_CAP=500          # 表格类响应默认截断行数
export AOS8_SESSION_IDLE_TIMEOUT_SECONDS=1800  # 空闲多久（秒）后自动登出并清缓存；0=禁用
export AOS8_SESSION_IDLE_SCAN_SECONDS=60       # 后台扫描间隔
export AOS8_DEVICES_CONFIG=/path/to/aos8.devices.yaml   # 可选

./scripts/start-aos8-mcp.sh
```

服务器上使用 **systemd** 时，可参考 `scripts/aos8-mcp.service.example` 修改 `User`、`WorkingDirectory`、`ExecStart` 路径后安装单元。

### 方式二：直接命令

```bash
cd aos8-mcp-server
export AOS8_MCP_HOST=0.0.0.0
export AOS8_MCP_PORT=8765
python -m aos8_mcp
# 或（已 pip install 到环境时）
aos8-mcp-server
```

MCP Streamable HTTP 端点：`http://<主机>:<端口>/mcp`

### Streamable HTTP 与会话头（排查 400 / Open WebUI）

协议顺序是：**先 `POST /mcp` 发 JSON-RPC `initialize`**，响应头里会有 **`mcp-session-id`**；之后的 **`GET`（SSE）或其它 `POST`** 须在请求头带上同一值：`Mcp-Session-Id: <上一步返回的 id>`。

因此仅用 **`curl` 发裸 `GET`** 会出现 **`400 Bad Request: Missing session ID`**，这是**预期行为**，不代表服务挂了。响应里若仍带 `mcp-session-id`，那是服务端为新会话分配的 id，**不会**自动当作你本次 GET 已提供的头。

可选环境变量 **`AOS8_MCP_STATELESS_HTTP=true`**：启用 FastMCP 的 **stateless** 模式（每请求独立 transport、不要求会话头），部分 Web UI 或简易探测更友好；若 Cherry Studio 等在 stateful 下已正常，可保持默认不开启。

## 开源 Chat UI 对接模板

以下字段名需替换为你的环境。具体 JSON 以你所用 UI 的「MCP HTTP / Streamable」配置为准。

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

若 UI 使用 **SSE 旧式** 或路径不同，请按其文档填写 `url` / `transport`。

### 扩展默认 show 命令

所有 `show` 预设都在 `aos8_mcp/show_registry.py` 的各 `*_PRESETS` 字典里维护，元素为 `ShowPreset(key, command, description, normalizer, cache_tier, needs_profile_name, profile_name_default)`：

- 想给已有领域增加变体：把新行追加到 `AP_PRESETS` / `WLAN_PRESETS` / `SYSTEM_PRESETS` / `NETWORK_PRESETS` / `AAA_PRESETS` / `CLUSTER_PRESETS` / `RF_PRESETS` / `CONTROLLERS_PRESETS` / `CLIENTS_PRESETS` / `LOG_PRESETS` 即可，工具表面无需改动。
- 想新增整组领域：建一个新的 `*_PRESETS`，再到 `DOMAINS` 字典里挂上去，并在 `server.py` 加一个对应的 `@mcp.tool()` 包一层 `_run_domain`。
- 想加更结构化的归一化输出：在 `aos8_mcp/normalize.py` 的 `_TABLE_CANDIDATE_KEYS` 注册顶层 key 候选；如果是异形结构，按 `_ssid_profile` 模式新增一个 `_xxx` 函数即可。

### 典型调用顺序（给模型或操作说明）

1. **`aos8_session_create_from_config`**（推荐）：可选 `config_path`；否则使用 `AOS8_DEVICES_CONFIG` 或 `./aos8.devices.yaml`。  
   或 **`aos8_session_create`**：在参数中传 `mm_ip`、`username`、`password`、`md_ips`、`verify_ssl`（**`false`** 跳过 TLS 校验，等价 `curl --insecure`）。
2. 不熟悉可选项时先调一次 **`aos8_catalog`** 或 `aos8_catalog(domain="aps")` 看预设清单。
3. 多次调用各领域工具或 `aos8_show`，均传入同一 `session_id`；模糊排错可直接用 **`aos8_ap_diagnose` / `aos8_client_diagnose` / `aos8_health_overview`** 一把抓。
4. `aos8_session_destroy`：`session_id`。

### 常用排障示例（给运维同事的"速查"）

| 场景 | 工具调用 |
| --- | --- |
| 平台总览 | `aos8_health_overview(session_id)` |
| AP 离线/状态 | `aos8_aps(session_id, variant="database", cli_suffix="\| include AP-M020")` 或 `aos8_ap_diagnose(session_id, ap_name="AP-M020")` |
| 终端排查 | `aos8_client_diagnose(session_id, identifier="aa:bb:cc:dd:ee:ff")` |
| 认证失败 | `aos8_aaa(session_id, variant="state_messages", cli_suffix="\| include <user_or_mac>")` |
| 集群状态 | `aos8_cluster(session_id, variant="lc_cluster_group_membership")` |
| 路由/L3 | `aos8_network(session_id, variant="ip_route")` |
| 系统资源 | `aos8_system(session_id, variant="cpuload")` / `variant="memory"` |
| RF 概览 | `aos8_rf(session_id, variant="arm_rf_summary")` |
| 最近错误日志 | `aos8_log(session_id, variant="errorlog", max_lines=100)` |
