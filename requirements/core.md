# Core Requirements

## MCP 通信 (`core/mcp.py`, `core/mcp_manager.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-001 | ✅ | 通过 MCP 协议连接 Chrome DevTools (`@anthropic/chrome-devtools-mcp`) |
| REQ-002 | ✅ | 自动连接已运行的 Chrome 实例（通过 `chrome://inspect/#remote-debugging`） |
| REQ-003 | ✅ | 通过 `document.cookie` 提取原始 Cookie 字符串，不做任何解析转换 |
| REQ-004 | ✅ | 支持 `--auto-connect` 标志跳过手动端口输入 |
| REQ-005 | 📋 | 支持 Firefox 和 Edge MCP 适配器 |
| REQ-005a | ✅ | 扫描 localStorage / sessionStorage 全部条目，以 `__auth__ls:` / `__auth__ss:` 前缀编码存储 |
| REQ-005b | ✅ | 捕获页面网络请求头，以 `__hdr__` 前缀编码存储（原始存取，不做公共头计算） |
| REQ-005c | ✅ | 捕获原始请求列表（URL + Method + Headers），以 `__raw__requests` 键存储 |
| REQ-005d | ✅ | 发现并记录关联域名（网络请求中出现的其他域名） |
| REQ-005e | ✅ | 处理 MCP `evaluate_script` 返回的双重编码 JSON（策略 2.5） |
| REQ-005f | ✅ | 登录状态检测：刷新页面后比较 URL，同域名重定向视为未登录 |
| REQ-005g | ✅ | 支持取消正在进行的抓取任务（`cancel_event`） |

## MCP 管理器 (`core/mcp_manager.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-101 | ✅ | 单例模式管理 MCP 连接，避免重复创建实例 |
| REQ-102 | ✅ | 支持两种浏览器模式：用户浏览器（连接已运行 Chrome）、临时浏览器（启动新 Chrome 实例） |
| REQ-103 | ✅ | 临时浏览器模式：自动启动 Chrome 并传入 CDP 远程调试端口 |
| REQ-104 | ✅ | 线程安全连接管理（`_comm_lock` RLock） |
| REQ-105 | ✅ | 空闲超时监控：超过 300 秒无活动自动断开 |
| REQ-106 | ✅ | 连接状态查询：`is_connected()`、`get_proc()`、`get_idle_seconds()` |
| REQ-107 | ✅ | 优雅断开：`disconnect()` 终止进程 + 停止监控线程 |

## JSON-RPC 通信 (`core/mcp.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-201 | ✅ | 构造标准 JSON-RPC 2.0 请求 |
| REQ-202 | ✅ | 发送请求到 MCP 进程 stdin，从 stdout 按行读取响应 |
| REQ-203 | ✅ | 30 秒超时保护，超时抛出 `McpTimeoutError` |
| REQ-204 | ✅ | 取消事件支持：`_jsonrpc_send` 可在等待时被取消 |
| REQ-205 | ✅ | 解析 Markdown 代码块中的 JSON 对象（`_extract_markdown_json_obj`，含 5 种解析策略） |

## MCP 工具调用 (`core/mcp.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-301 | ✅ | `list_pages`：获取浏览器页面列表 |
| REQ-302 | ✅ | `select_page`：选择目标页面 |
| REQ-303 | ✅ | `navigate_page`：刷新 / 导航页面 |
| REQ-304 | ✅ | `list_network_requests`：获取网络请求列表 |
| REQ-305 | ✅ | `get_network_request`：获取单个请求详情（含响应头） |
| REQ-306 | ✅ | `evaluate_script`：在页面执行 JavaScript 采集 Cookie 和 Storage |

## Vault 存储 (`core/vault.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-401 | ✅ | 使用 Romek Vault 加密持久化存储会话数据 |
| REQ-402 | ✅ | 启动时从 OS keyring 自动获取 Vault 主密码 |
| REQ-403 | ✅ | CRUD 操作：`list_sessions`、`get_session`、`store_session`、`delete_session` |
| REQ-404 | ✅ | 每个域名对应一个 Vault 条目（后写覆盖语义） |
| REQ-405 | ✅ | 会话默认 30 天过期 |
| REQ-406 | 📋 | 导出 Cookies 为 Netscape `cookies.txt` 格式 |
| REQ-407 | 📋 | 从浏览器扩展或 JSON 导入 Cookies |

## 会话管理 (`core/session.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-501 | ✅ | 统一公开 API：`grab_cookies`、`grab_and_store`、`list_sites`、`get_site`、`delete_site` |
| REQ-502 | ✅ | 认证凭据编码：`_encode_auth_tokens(cookies: str, auth_tokens: list)` → `{__raw__cookie, __auth__ls:*, __auth__ss:*}` |
| REQ-503 | ✅ | 认证凭据解码：`_decode_auth_tokens(cookies: dict)` → `(raw_cookie: str, auth_tokens: list)` |
| REQ-504 | ✅ | 请求头编码：`__hdr__` 前缀，原始请求列表 `__raw__requests` |
| REQ-505 | ✅ | 关联域名存储与查询 |
| REQ-506 | ✅ | `list_sites` 返回摘要信息（cookie 数、凭据数、header 数、关联域名数、过期时间） |
| REQ-507 | ✅ | `get_site` 返回完整详情（原始 Cookie 字符串、凭据列表、headers、原始请求、关联域名） |
| REQ-508 | ✅ | 所有符号在 `core/__init__.py` 中导出 |
| REQ-509 | ✅ | 原始 URL 记录：`__original_url__` 键，`_encode_url` / `_decode_url` 辅助函数 |
| REQ-510 | ✅ | `store_site` 接受 `original_url` 参数，编码后存入 Vault |
| REQ-511 | ✅ | `list_sites` / `get_site` 返回 `original_url` 字段 |
| REQ-512 | ✅ | 站点更新时使用原始 URL 导航（而非纯域名），回退到域名 |