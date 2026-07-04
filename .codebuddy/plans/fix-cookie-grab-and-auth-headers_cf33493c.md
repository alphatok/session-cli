---
name: fix-cookie-grab-and-auth-headers
overview: 增强 Cookie 抓取 JS 脚本，同时从 localStorage / sessionStorage 扫描认证 Token，更新端到端的数据流（MCP → Session → Vault → CLI/Web UI）
todos:
  - id: enhance-mcp-grab
    content: "enhance core/mcp.py: replace evaluate_script JS to collect cookies + localStorage + sessionStorage, add _extract_markdown_json_obj parser, return enriched dict"
    status: completed
  - id: update-session-crud
    content: "update core/session.py: store_site encodes auth_tokens with __auth__ prefix, get_site decodes them back, list_sites counts both"
    status: completed
    dependencies:
      - enhance-mcp-grab
  - id: update-cli-display
    content: "update main.py: cmd_grab adapts to new return type, cmd_get displays auth_tokens section"
    status: completed
    dependencies:
      - enhance-mcp-grab
  - id: update-web-server
    content: "update server.py and templates/index.html: _run_grab_task adapts, detail view shows auth_tokens panel"
    status: completed
    dependencies:
      - update-session-crud
  - id: update-tests
    content: "update tests/conftest.py, test_mcp.py, test_session.py: new fixtures for JSON object extraction and auth token encode/decode"
    status: completed
    dependencies:
      - update-session-crud
  - id: update-requirements-doc
    content: "update requirements/core.md: correct REQ-003 status to reflect actual cookie attribute limitations"
    status: completed
---

## 用户需求

当前 session-cli 的 Cookie 抓取功能存在两个严重缺陷，需要修复：

### 1. Cookie 抓取不完整

- 当前只用 `document.cookie` 获取 Cookie，只能拿到 `name=value`，丢失了 `domain`、`path`、`httpOnly`、`secure`、`sameSite`、`expires` 等所有 Cookie 属性
- 由于 `document.cookie` 的限制，httpOnly Cookie 完全无法获取

### 2. 未采集认证授权凭据

- 完全不扫描 `localStorage` 和 `sessionStorage` 中常见的认证 Token（如 `Authorization`、`Bearer`、`token`、`jwt`、`access_token`、`refresh_token` 等）
- 不识别 Cookie 中携带的认证相关字段

## 修复目标

1. 增强 `core/mcp.py` 中 `grab_cookies` 的 JS 脚本，从单纯调用 `document.cookie` 升级为全面采集：

- 所有 Cookie 的 name/value 对
- localStorage 中匹配认证模式的 key-value
- sessionStorage 中匹配认证模式的 key-value

2. 更新数据模型，将认证凭据与普通 Cookie 区分存储，在 CLI 和 Web UI 中清晰展示
3. 更新 `requirements/core.md` 中 REQ-003 的状态，如实反映限制

## 技术方案

### 核心思路

由于 `chrome-devtools-mcp` 工具集中没有 CDP 级别的 Cookie 工具，`document.cookie` 又无法获取 Cookie 属性，因此采用两阶段策略：

**阶段一（本次实现）**：在 `evaluate_script` 中执行增强版 JS，收集 Cookie name/value + localStorage/sessionStorage 中的认证凭据。将认证凭据以 `__auth__` 前缀编码存入 romek Vault（保持现有 `Dict[str, str]` schema 不变），读取时自动解码分离展示。

**阶段二（后续改进）**：引入 CDP `Network.getCookies` 获取完整 Cookie 属性（domain/path/httpOnly/secure/sameSite/expires），方案另行规划。

### 数据流变更

```
Before:
  evaluate_script(() => document.cookie)
  → "a=1; b=2"
  → {"a": "1", "b": "2"}  (Dict[str, str])
  → vault.store_session(domain, cookies)

After:
  evaluate_script(() => {cookies + localStorage + sessionStorage})
  → {"cookies": [...], "storage": {"localStorage": {...}, "sessionStorage": {...}}}
  → 解析为 {"cookies": Dict, "auth_tokens": List}
  → vault: cookies 原样存储, auth_tokens 以 __auth__ 前缀编码进 cookies dict
  → get_site 时自动解码分离
```

### 认证凭据编码规则

为避免与真实 Cookie 名冲突，使用 `__auth__` 前缀标记：

| 来源 | Vault Key 格式 | 示例 |
| --- | --- | --- |
| localStorage | `__auth__ls:{key}` | `__auth__ls:auth_token` |
| sessionStorage | `__auth__ss:{key}` | `__auth__ss:session_id` |


### 涉及文件

| 文件 | 修改类型 | 说明 |
| --- | --- | --- |
| `core/mcp.py` | MODIFY | 增强 JS 脚本 + 新增 `_extract_markdown_json_obj` + 变更返回值 |
| `core/session.py` | MODIFY | `store_site` 编码 auth_tokens，`get_site` 解码，`list_sites` 统计 |
| `main.py` | MODIFY | `cmd_grab` 适配新返回值，`cmd_get` 展示 auth_tokens |
| `server.py` | MODIFY | `_run_grab_task` 适配新数据结构 |
| `templates/index.html` | MODIFY | 详情弹窗展示 auth_tokens 区域 |
| `tests/conftest.py` | MODIFY | 新增 fixture，更新已有 fixture |
| `tests/test_mcp.py` | MODIFY | 新增 JSON 对象提取测试 |
| `tests/test_session.py` | MODIFY | 新增 auth_token 编解码测试 |
| `requirements/core.md` | MODIFY | REQ-003 状态修正 |