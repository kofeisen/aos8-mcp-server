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

- **会话模型 B**：`aos8_session_create_from_config`（读本地 YAML）或 `aos8_session_create`（参数传入）登录 MM → 多次工具调用复用 `session_id` → `aos8_session_destroy` 注销并清缓存。
- **执行策略**：默认在 **MM** 上执行；若响应中含 *This command is not applicable on conductor switch*，则按配置中 **MD 顺序** 在对应 MD 上登录并重试。
- **领域工具**（均可选 `cli_suffix` 追加 `| include` 等）：`aos8_controllers`、`aos8_clients`、`aos8_aps`、`aos8_log`、`aos8_wlan`，另提供通用 `aos8_show`。
- **响应**：始终包含 **`raw`**（设备返回解析结果），并附带 **`normalized`** 启发式摘要（不改变 `raw`）。
- **缓存**：同 `session_id` + 目标 IP + 完整命令字符串，在进程内缓存一段时间（默认 60s，可用环境变量调整）。

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
export AOS8_CACHE_TTL_SECONDS=60
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

- **通用领域**：在 `aos8_mcp/show_registry.py` 的 `DOMAIN_SPECS` 中增加或修改条目；`normalizer` 见 `aos8_mcp/normalize.py`。
- **`show ap` 子命令**：在 `AP_SHOW_VARIANTS` 中增加一行，或通过 `aos8_aps(..., variant="键名")` 调用；键名列表可用 MCP 工具 **`aos8_ap_show_variants`** 查询。

### 典型调用顺序（给模型或操作说明）

1. **`aos8_session_create_from_config`**（推荐）：可选 `config_path`；否则使用 `AOS8_DEVICES_CONFIG` 或 `./aos8.devices.yaml`。  
   或 **`aos8_session_create`**：在参数中传 `mm_ip`、`username`、`password`、`md_ips`、`verify_ssl`（**`false`** 跳过 TLS 校验，等价 `curl --insecure`）。
2. 多次调用各领域工具或 `aos8_show`，均传入同一 `session_id`。
3. `aos8_session_destroy`：`session_id`。
