# Session CLI

> 通过 Chrome DevTools MCP 协议自动抓取和管理浏览器 Session/Cookie。支持 CLI 和 Web UI，加密存储。

[English](README.md)

## 解决什么问题？

在写脚本、爬虫或 API 测试时，手动从浏览器提取 Cookie 非常繁琐 — 打开 DevTools → Application 面板 → 一个个复制，每个域名都要重复一遍。

Session CLI 通过 Chrome 远程调试协议（MCP）自动化这一过程。一条命令即可抓取指定域名所有 Cookie，存入加密 Vault 中随时取用。

## 功能特性

- **CLI + Web UI** — 终端或浏览器都能操作
- **Python SDK** — `query_session()` 程序化查询接口，支持子域名智能匹配
- **MCP 协议** — 通过标准 Chrome DevTools MCP 适配器与 Chrome 通信
- **加密存储** — 所有数据存入 Romek Vault，通过系统 Keyring 自动解锁
- **SSE 实时推送** — Web 界面实时显示抓取进度
- **开箱即用** — `uv run python main.py` 即可运行

## 快速开始

### 环境要求

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Chrome 浏览器，需开启远程调试（`chrome://inspect/#remote-debugging`）
- Node.js 18+（供 `npx` 运行 MCP 适配器）

### 安装

```bash
git clone https://github.com/<user>/session-cli.git
cd session-cli
uv sync
```

### CLI 使用

```bash
# 列出已存储的站点
uv run python main.py list

# 抓取指定域名的 Cookie
uv run python main.py grab example.com --auto-connect

# 查看已抓取的 Cookie
uv run python main.py get example.com

# 删除站点
uv run python main.py delete example.com
```

### Web UI

```bash
uv run python main.py serve
# → 打开 http://127.0.0.1:8000
```

## 命令速查

| 命令 | 说明 |
|------|------|
| `list` | 列出所有已存储的站点 |
| `grab <域名> --auto-connect` | 从 Chrome 抓取 Cookie 并存储 |
| `get <域名>` | 查看某域名的 Cookie 详情 |
| `delete <域名>` | 删除已存储的站点 |
| `serve` | 启动 FastAPI Web 界面 |

## 项目结构

```
session-cli/
├── core/
│   ├── __init__.py      # 公共 API
│   ├── mcp.py           # Chrome DevTools MCP 通信层
│   ├── vault.py         # Romek Vault 加密持久化
│   └── session.py       # 业务逻辑（抓取 + 存储）
├── main.py              # CLI 入口
├── server.py            # FastAPI Web 服务
├── templates/
│   └── index.html       # HTMX 前端页面
├── tests/               # Pytest 测试套件
├── requirements/        # 需求文档
├── pyproject.toml
└── README.md
```

## 架构

```
┌───────────┐     ┌──────────┐
│    CLI    │     │  Web UI  │
│  main.py  │     │ server.py│
└─────┬─────┘     └────┬─────┘
      │                │
      └───────┬────────┘
              ▼
      ┌──────────────┐
      │     core     │
      ├──────────────┤
      │ grab_cookies  │ ◄── MCP + Chrome autoConnect
      │ query_session │ ◄── 只读查询（子域名匹配）
      │ list_sites    │ ◄── Romek Vault CRUD
      │ store_site    │
      │ delete_site   │
      └──────────────┘
```

## 常见问题

### 1. 需要保持 Chrome 开着吗？

需要。Session CLI 通过 Chrome DevTools 协议（MCP）与浏览器通信。Chrome 必须保持运行，且 `chrome://inspect/#remote-debugging` 处于开启状态。

### 2. 数据存储安全吗？

所有 Session 数据存储在 Romek Vault 加密文件库中。Vault 密码在启动时自动从系统 Keyring 获取，无需手动输入。

### 3. 为什么 `--auto-connect` 有时会失败？

MCP 适配器会自动发现 Chrome 的调试端口。如果失败，请确保 Chrome 启动时已开启远程调试（例如添加 `--remote-debugging-port=9222` 参数），且该端口未被其他程序占用。

### 4. 支持除 Chrome 以外的浏览器吗？

目前仅支持 Chrome，通过 `@anthropic/chrome-devtools-mcp` 适配器实现。Firefox 和 Edge 支持已在规划中（详见[需求文档](requirements/core.md)）。

### 5. 如何在 Python 脚本中使用已抓取的 Cookie？

使用 `query_session()` 获取简洁稳定的 dict 结果，自动支持子域名匹配：

```python
from core import query_session

result = query_session("api.example.com")
# {
#     "found": True,
#     "domain": "example.com",        # 实际匹配到的存储域名
#     "matched_by": "subdomain",      # "exact" | "subdomain"
#     "cookies": "token=abc; uid=123",
#     "headers": {"Authorization": "Bearer xxx"},
#     "auth_tokens": [{"source": "localStorage", "key": "token", "value": "..."}],
#     "expired": False,
#     "expires_at": "2026-08-01T12:00:00",
# }

if result["found"]:
    print(result["cookies"])
    print(result["headers"])
```

完整 API 参考见 `core/session.py`（支持 URL 自动清洗、子域名回退、过期数据过滤）。

## License

MIT
