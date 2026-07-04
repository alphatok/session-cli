# Server Requirements

## Web 框架 (`server.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-701 | ✅ | 使用 FastAPI 构建 Web API |
| REQ-702 | ✅ | 使用 uvicorn 运行 HTTP 服务（`127.0.0.1:8000`） |
| REQ-703 | ✅ | 生命周期管理：启动时校验 Vault，关闭时清理 MCP 连接 + SSE 队列 |
| REQ-704 | ✅ | 优雅关闭：Ctrl+C 后无 traceback，输出清理日志 |
| REQ-705 | ✅ | 关闭时通过 `_shutdown_event` 通知 SSE 生成器退出 |
| REQ-706 | ✅ | 关闭时直接 kill MCP 进程（避免 `_comm_lock` 阻塞） |
| REQ-707 | ✅ | 全局 `_shutdown_event` 信号：SSE 生成器检测后立即退出循环 |
| REQ-708 | ✅ | 生命周期启动时重置 `_shutdown_event`（防止测试残留） |
| REQ-709 | ✅ | 刷新站点时使用 `original_url`（若存储过），否则回退到域名 |

## API 路由

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-711 | ✅ | `GET /` — 返回 HTMX 前端页面 |
| REQ-712 | ✅ | `GET /api/sessions` — 列出所有站点（JSON） |
| REQ-713 | ✅ | `GET /api/sessions/{domain}` — 查看站点详情（JSON） |
| REQ-714 | ✅ | `POST /api/sessions/grab?domain=` — 启动抓取任务，返回 `task_id` |
| REQ-715 | ✅ | `GET /api/sessions/grab/progress?task_id=` — SSE 流式推送抓取进度 |
| REQ-716 | ✅ | `POST /api/sessions/grab/{task_id}/cancel` — 取消抓取任务 |
| REQ-717 | ✅ | `DELETE /api/sessions/{domain}` — 删除站点 |
| REQ-718 | ✅ | `POST /api/sessions/{domain}/refresh` — 刷新已有站点 |
| REQ-719 | ✅ | `GET /api/mcp/status` — 查询 MCP 连接状态 |
| REQ-720 | ✅ | `POST /api/mcp/connect?browser_mode=` — 连接 MCP |
| REQ-721 | ✅ | `POST /api/mcp/disconnect` — 断开 MCP |
| REQ-722 | ✅ | `GET /api/logs/stream` — SSE 流式推送全局日志 |

## SSE 流式推送

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-731 | ✅ | 抓取进度 SSE：按阶段推送（waiting → listing → found → navigating → evaluating → done） |
| REQ-732 | ✅ | 抓取进度 SSE：使用 `asyncio.to_thread()` 避免 `queue.Queue.get()` 阻塞事件循环 |
| REQ-733 | ✅ | 抓取进度 SSE：检测 `_shutdown_event` 信号后立即退出循环 |
| REQ-734 | ✅ | 日志 SSE：先发送历史日志（最多 200 条），再持续推送新日志 |
| REQ-735 | ✅ | 日志 SSE：同样使用 `asyncio.to_thread()` 避免阻塞事件循环 |
| REQ-736 | ✅ | 日志 SSE：检测 `_shutdown_event` 信号后立即退出循环 |

## 全局日志

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-741 | ✅ | 全局日志队列（`threading.Queue`），服务端 + 前端均可消费 |
| REQ-742 | ✅ | 日志条目格式：`{time, stage, detail}` |
| REQ-743 | ✅ | 日志阶段类型：`system`、`task`、`mcp`、`error`、`completed`、`cancelled` |
| REQ-744 | ✅ | 历史日志保留最近 200 条，新连接先回放历史再推送实时 |
| REQ-745 | ✅ | 线程安全的日志发射（`_log_lock`） |

## 并发任务管理

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-751 | ✅ | 每个抓取任务分配唯一 `task_id`（UUID） |
| REQ-752 | ✅ | 每个任务拥有独立的 `queue.Queue` 用于 SSE 进度推送 |
| REQ-753 | ✅ | 每个任务拥有独立的 `cancel_event` 用于取消操作 |
| REQ-754 | ✅ | 抓取任务在后台线程（daemon）中执行，不阻塞 API 响应 |
| REQ-755 | ✅ | 任务完成后自动清理队列和活跃任务记录 |