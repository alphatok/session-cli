# 日志模块 + CDP 浏览器选择 计划

## 当前状态分析

### 现状
- **SSE 进度流**：`server.py` 中 `_run_grab_task` 通过 `queue.Queue` → `/api/sessions/grab/progress` SSE 端点单向推送进度到前端
- **MCP 连接**：`McpManager.connect()` 硬编码 `auto_connect=True`，始终使用用户已登录的浏览器
- **无日志**：错误和中间过程只在 SSE 中推送，不输出到 console 或持久化
- **无浏览器选择**：无法切换临时浏览器模式

### 涉及文件
- `server.py` — SSE 端点、MCP 连接 API、日志 API
- `core/mcp.py` — `_start_mcp_server` 函数
- `core/mcp_manager.py` — `McpManager` 类
- `templates/index.html` — 前端 UI

---

## 功能一：全局日志模块

### 1.1 后端：全局日志队列 + SSE 端点

**修改 `server.py`**：

- 新增全局 `_log_queue: queue.Queue`，所有日志事件写入此队列
- 新增 `_log_history: list`（最多保留 200 条），新连接时同步历史
- 新增 `_emit_log(stage: str, detail: str)` 函数：同时写入 `_log_queue`、`_log_history`、`print()` 到 console
- 修改 `_run_grab_task` 的 `on_progress` 回调，在 `q.put()` 的同时也调用 `_emit_log()`
- 修改 `_run_grab_task` 的 `except` 分支，error/cancelled 也调用 `_emit_log()`
- 新增 `_emit_log` 也在 `api_mcp_connect`、`api_mcp_disconnect` 中调用
- 新增 `/api/logs/stream` SSE 端点：先发送历史日志，再持续推送新日志
- 新增 `/api/logs/recent` HTTP 端点：返回最近日志列表

### 1.2 前端：日志面板

**修改 `templates/index.html`**：

- 在页面底部（container 内、站点列表下方）新增一个可折叠的日志面板
- 面板结构：标题栏（"📋 运行日志" + 折叠/展开按钮 + 清除按钮 + 日志计数）
- 面板内容：`<div id="log-panel">` 滚动区域，显示日志条目
- 日志条目格式：`[时间] [阶段标签] 详情`，阶段标签使用不同颜色（error=红色, completed=绿色, cancelled=橙色, 其他=灰色）
- 通过 `EventSource` 连接 `/api/logs/stream`，实时追加日志
- 新增 CSS 样式：终端风格（等宽字体、暗色背景、滚动条美化）

---

## 功能二：CDP 浏览器选择

### 2.1 后端：MCP 支持浏览器模式切换

**修改 `core/mcp.py`**：

- 修改 `_start_mcp_server` 签名：`_start_mcp_server(auto_connect: bool = True, browser_url: Optional[str] = None)`
  - 当 `browser_url` 指定时，使用 `--browser-url={browser_url}` 而非硬编码 `http://127.0.0.1:9222`
- 新增 `_launch_temp_chrome(port: int = 9222) -> subprocess.Popen` 函数：
  - 创建临时 user-data-dir（`tempfile.mkdtemp`）
  - 查找 Chrome 可执行文件路径（Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe` 等）
  - 启动 Chrome：`chrome.exe --remote-debugging-port=9222 --user-data-dir=<temp> --no-first-run --no-default-browser-check`
  - 返回 subprocess.Popen 句柄

**修改 `core/mcp_manager.py`**：

- `McpManager` 新增属性：`_browser_mode: str = "user"`（"user" | "temp"）、`_temp_chrome_proc: Optional[subprocess.Popen]`
- 修改 `connect()` 签名：`connect(browser_mode: str = "user")`
  - `"user"` 模式：调用 `_start_mcp_server(auto_connect=True)`
  - `"temp"` 模式：先调用 `_launch_temp_chrome()`，再调用 `_start_mcp_server(auto_connect=False, browser_url="http://127.0.0.1:9222")`
- 修改 `_disconnect_internal()`：如果 `_temp_chrome_proc` 存在，终止它
- 修改 `get_status()` 返回值：增加 `browser_mode` 字段
- 新增 `set_browser_mode(mode: str)` 方法
- 修改 `grab_cookies_managed`：在 `ensure_connected` 前检查 browser_mode 是否变化

**修改 `server.py`**：

- `api_mcp_connect` 增加 `browser_mode` 查询参数
- `api_mcp_status` 返回 `browser_mode` 字段
- 在连接/断开时通过 `_emit_log` 记录日志

### 2.2 前端：浏览器模式选择器

**修改 `templates/index.html`**：

- 在 MCP 状态栏中，连接按钮左侧增加一个下拉选择器：
  - "👤 用户浏览器"（默认）
  - "🆕 临时浏览器"
- 点击"连接"按钮时，读取当前选择的模式，传给 `/api/mcp/connect?browser_mode=user` 或 `?browser_mode=temp`
- 状态栏显示当前使用的浏览器模式

---

## 修改步骤

### 步骤 1：修改 `core/mcp.py` — `_start_mcp_server` 支持 browser_url

### 步骤 2：新增 `core/mcp.py` — `_launch_temp_chrome`

### 步骤 3：修改 `core/mcp_manager.py` — `McpManager` 支持 browser_mode

### 步骤 4：修改 `server.py` — 全局日志队列 + 日志 API

### 步骤 5：修改 `server.py` — MCP API 支持 browser_mode

### 步骤 6：修改 `templates/index.html` — 日志面板（CSS + HTML + JS）

### 步骤 7：修改 `templates/index.html` — 浏览器模式选择器（CSS + HTML + JS）

---

## 验证方式

1. 启动服务，打开页面 → 日志面板可见，显示 "[系统] 服务已启动" 等初始化日志
2. 选择"临时浏览器" → 点击连接 → 自动打开新的 Chrome 窗口 → 日志显示 "临时浏览器已启动"
3. 输入域名抓取 → 日志面板实时显示所有中间步骤和结果
4. 切换到"用户浏览器" → 断开再连接 → 使用用户已登录的浏览器
5. 抓取失败 → 错误信息同时出现在 console、日志面板、Toast 中