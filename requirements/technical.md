# Technical Requirements

## 技术栈

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-901 | ✅ | Python 3.12+ |
| REQ-902 | ✅ | 依赖管理：uv + pyproject.toml |
| REQ-903 | ✅ | 测试框架：pytest + pytest-asyncio |
| REQ-904 | ✅ | Web 框架：FastAPI + uvicorn |
| REQ-905 | ✅ | 前端：HTMX + 原生 HTML/CSS/JS |
| REQ-906 | ✅ | 加密存储：Romek Vault |
| REQ-907 | ✅ | 密码管理：OS keyring |
| REQ-908 | ✅ | CDP 通信：chrome-devtools-mcp (npm 包，通过 MCP 协议) |

## 非功能需求

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-911 | ✅ | 全部 133 个单元测试通过 |
| REQ-912 | ✅ | 服务端优雅关闭：Ctrl+C 后 1 秒内释放资源 |
| REQ-913 | ✅ | 线程安全：多线程访问 MCP 连接、日志队列、SSE 队列均有锁保护 |
| REQ-914 | ✅ | 错误处理：所有异常均被捕获并输出中文错误信息 |
| REQ-915 | ✅ | 原始存取原则：Cookie 和 Header 原样存储，不做转换或解析 |

## CSS 设计系统

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-921 | ✅ | CSS 变量体系：颜色（`--surface-hover`、`--border-light`）、光晕（`--accent-glow`、`--green-glow`、`--red-glow`）、阴影（`--shadow-sm/md/lg`）、过渡时间（`--transition-fast/normal/slow`） |
| REQ-922 | ✅ | 设计风格：简洁、极简、Apple 风格 |

## 输入框交互

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-931 | ✅ | Hover：主题色边框 + 3px 光晕（Google Gemini 极光风格） |
| REQ-932 | ✅ | Focus：4px 光晕 + 20px 扩散光晕（Google Gemini 风格） |
| REQ-933 | ✅ | 光晕效果为非旋转式 |

## 按钮交互

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-941 | ✅ | Hover：轻微上移 + 阴影扩展 + 流光动画 |
| REQ-942 | ✅ | Active：回弹效果 + 阴影收缩 |
| REQ-943 | ✅ | 主按钮 hover 时亮度提升 |
| REQ-944 | ✅ | 危险按钮 hover 时添加红色背景光晕 |

## 卡片交互

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-951 | ✅ | Hover：边框亮度增强 + 阴影增强 |

## 列表项交互

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-961 | ✅ | Hover：背景变化 + 右移微动 |
| REQ-962 | ✅ | 操作按钮默认隐藏，hover 时淡入显示 |

## 进度条

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-971 | ✅ | 5px 高度 |
| REQ-972 | ✅ | shimmer 流光动画 |

## 状态指示灯

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-981 | ✅ | 10px 尺寸 |
| REQ-982 | ✅ | 已连接状态：双层光晕增强效果 |
| REQ-983 | ✅ | 连接中状态：缩放动画 |

## 测试覆盖

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-991 | ✅ | 核心模块测试：`test_mcp.py` — MCP 通信、JSON-RPC、Cookie 抓取 |
| REQ-992 | ✅ | 会话模块测试：`test_session.py` — 编码/解码、CRUD、列表格式化 |
| REQ-993 | ✅ | 服务端测试：`test_server.py` — API 路由、SSE 流、任务管理 |
| REQ-994 | ✅ | 测试隔离：每个测试使用独立的 Vault 实例，不相互影响 |