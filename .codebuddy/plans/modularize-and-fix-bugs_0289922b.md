---
name: modularize-and-fix-bugs
overview: 将 session_core.py 拆分为 mcp.py/vault.py/session.py 三个模块；修复 12 个 bug（包括全局状态竞态、vault 重复关闭、已废弃 API、SSE 内存泄漏等）；为每个模块编写单元测试。
todos:
  - id: explore-romek-api
    content: 使用 [subagent:code-explorer] 深入探索 romek Vault API 的 close() 行为和 unlock 签名，确认正确的修复方向
    status: completed
  - id: create-core-package
    content: 创建 core/ 包结构：__init__.py 统一导出、mcp.py 提取 MCP 通信层、vault.py 提取 VaultManager 类、session.py 提取业务逻辑层
    status: completed
    dependencies:
      - explore-romek-api
  - id: fix-critical-bugs
    content: 修复 4 个严重 bug：Vault 重复 close（#1）、init 初始化死锁（#2）、_send_mcp 响应丢失（#3）、SSE 队列内存泄漏（#4）
    status: completed
    dependencies:
      - create-core-package
  - id: fix-medium-bugs
    content: 修复 6 个中等 bug：类型注解（#5）、datetime.utcnow（#6）、on_event 废弃（#7）、cookie 正则（#8）、参数解析（#9）、StaticFiles 导入（#10）
    status: completed
    dependencies:
      - create-core-package
  - id: fix-maintainability
    content: 修复 2 个可维护性问题：CSS.escape 中文域名（#11）、npx 跨平台路径查找（#12）
    status: completed
    dependencies:
      - create-core-package
  - id: write-tests
    content: 编写 pytest 测试：conftest.py fixtures、test_mcp.py、test_vault.py、test_session.py、test_server.py，覆盖核心逻辑和 bug 修复验证
    status: completed
    dependencies:
      - fix-critical-bugs
      - fix-medium-bugs
  - id: update-imports
    content: 更新 main.py 和 server.py 的 import 路径，从 session_core 迁移到 core 包，删除 session_core.py
    status: completed
    dependencies:
      - create-core-package
  - id: add-deps-and-verify
    content: 添加 pytest 依赖到 pyproject.toml，运行全量测试验证所有修复通过
    status: completed
    dependencies:
      - write-tests
      - update-imports
---

## 用户需求

将当前单体 `session_core.py`（307行）按职责拆分为模块化包结构，修复已识别的 12 个 bug（含 4 个严重竞态/数据正确性 bug），并为核心模块编写 pytest 单元测试。

## 核心功能

- **模块化拆分**：将 MCP 通信、Vault 管理、Cookie 抓取与 CRUD 分离到 `core/` 包的独立子模块中
- **Bug 修复**：解决 Vault 重复关闭导致后续调用失败、init 初始化死锁、SSE 队列内存泄漏、MCP 响应丢失等严重问题
- **测试覆盖**：为核心模块编写 pytest 单元测试，覆盖 Vault 生命周期、MCP 协议解析、CRUD 操作和 SSE 清理

## 技术栈

- Python 3.13 + FastAPI + uv 包管理
- pytest（测试框架）+ pytest-asyncio（异步测试）
- Romek Vault（Cookie 加密存储）
- chrome-devtools-mcp（Chrome 144+ autoConnect）

## 架构设计

### 拆分前（现状）

```
session_core.py (307行, 单体文件)
  ├── _NPX_CMD 查找
  ├── _send_mcp / _start_mcp_server / _extract_result
  ├── grab_cookies()
  ├── _vault 单例 + get_vault / unlock_vault / init_vault
  └── list_sites / get_site / store_site / delete_site
```

### 拆分后（目标）

```
core/
  ├── __init__.py      # 公共 API: grab_cookies, list_sites, get_site, store_site, delete_site, get_vault, init_vault, unlock_vault
  ├── mcp.py           # MCP 通信层 (~90行)
  │   ├── _NPX_CMD 自动查找（支持 Win/Linux/macOS）
  │   ├── _send_mcp() → 修复响应丢失 bug
  │   ├── _start_mcp_server()
  │   ├── _extract_result()
  │   └── _extract_json_from_markdown() → 修复正则 bug
  ├── vault.py         # Vault 管理层 (~70行)
  │   ├── VaultManager 类（替代全局可变 _vault）
  │   │   ├── 生命周期: init → unlock → use → 无需手动 close
  │   │   ├── 避免 CRUD 操作中重复 close() bug
  │   │   └── 线程安全锁
  │   └── reset_vault() 测试辅助函数
  └── session.py       # 业务逻辑层 (~100行)
      ├── grab_cookies() → 参数化 domain / auto_connect / on_progress
      ├── list_sites()
      ├── get_site()
      ├── store_site()
      └── delete_site()

main.py    → from core import ...（替换 import session_core）
server.py  → from core import ...（替换 import session_core）
```

### 数据流

```
Web UI (server.py) / CLI (main.py)
    │
    ▼
core/__init__.py  (统一入口)
    ├── core/mcp.py     ← npx→chrome-devtools-mcp→CDP→Chrome
    ├── core/vault.py   ← Romek Vault (AES-256 encrypted SQLite)
    └── core/session.py ← 协调 mcp + vault
```

## 实现详情

### Bug 修复详情

| # | Bug | 修复方案 |
| --- | --- | --- |
| 1 | Vault 重复 close() | 引入 VaultManager 类，移除 CRUD 方法中的 close() 调用，Vault 连接由 Manager 生命周期管理 |
| 2 | cmd_init() 无法创建新 vault | get_vault() 不再对未初始化 vault 抛异常，改为返回未解锁 vault；cmd_init 显式调用 init_vault() |
| 3 | _send_mcp 响应丢失 | 改为无限循环 + 超时机制，持续读取直到匹配 id 的响应出现或超时 |
| 4 | SSE 队列内存泄漏 | grab 完成后（completed/error），清理 _progress_queues 中的条目 |
| 5 | callable 类型注解 | 改为 `Optional[Callable[[str, str], None]]` |
| 6 | datetime.utcnow() | 改为 `datetime.now(datetime.UTC)` |
| 7 | on_event("startup") | 改用 `@app.router.lifespan` 上下文管理器 |
| 8 | cookie 正则 | 增加 fallback：直接提取 `"..."` 双引号内容，不依赖 markdown code block |
| 9 | walrus 参数解析 | 拆分为明确的 for 循环：先收集 args，再检测 --auto-connect 标志 |
| 10 | StaticFiles 导入 | 移除未使用的 import |
| 11 | CSS.escape 中文域名 | 对 domain 中的非 ASCII 字符做 encodeURIComponent 处理 |
| 12 | npx 仅 Windows | 增加 Linux/macOS 路径查找：`/usr/local/bin/npx`、`which npx` |


### 目录结构

```
session-cli/
├── core/
│   ├── __init__.py      # [NEW] 统一导出公共 API
│   ├── mcp.py           # [NEW] MCP JSON-RPC 通信层
│   ├── vault.py         # [NEW] Vault 管理器（VaultManager 类）
│   └── session.py       # [NEW] Cookie 抓取 + CRUD 操作
├── main.py              # [MODIFY] 改用 from core import ...
├── server.py            # [MODIFY] 改用 from core import ...，修复 startup/bug
├── templates/
│   └── index.html       # [MODIFY] 修复 CSS.escape 中文域名
├── tests/
│   ├── __init__.py      # [NEW]
│   ├── conftest.py      # [NEW] pytest fixtures（mock romek Vault）
│   ├── test_mcp.py      # [NEW] MCP 通信测试
│   ├── test_vault.py    # [NEW] VaultManager 测试
│   ├── test_session.py  # [NEW] CRUD + grab 流程测试
│   └── test_server.py   # [NEW] FastAPI 路由 + SSE 清理测试
├── pyproject.toml       # [MODIFY] 添加 pytest, pytest-asyncio, pytest-mock
├── session_core.py      # [DELETE] 已拆分到 core/
└── uv.lock
```

## SubAgent

- **code-explorer**
- Purpose: 在实现过程中深入探索 romek Vault API 的详细行为（如 close() 后是否可重用、unlock 签名），确保 bug 修复方案在 romek 库层面可行
- Expected outcome: 确认 Vault 的正确使用模式，避免修复方案与 romek 内部实现冲突

## Skill

- **karpathy-guidelines**
- Purpose: 在编码过程中遵循精简原则，避免过度抽象；确保每次修改都是外科手术式的，不引入不必要的重构
- Expected outcome: 代码改动最小化、精确化，每个修复都有对应的测试覆盖