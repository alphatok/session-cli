# 修复 double-encoded JSON 解析 + 原始存取

## CDP 分析结论

通过 CDP 在 deepseek 页面执行 `_GRAB_JS`：

- **页面状态**：正常加载，未重定向；`document.cookie` 有 2 个 Cookie，localStorage 中有 userToken、settingsJwt 等有效凭据
- **JS 返回**：`{"cookies":[...], "storage":{...}}`
- **MCP 包装**：`"{\"cookies\":[...],\"storage\":{...}}"` ← double-encoded JSON 字符串

### 根因

`evaluate_script` MCP 工具将 JS 返回值 double-encode：

```
JS 返回:  {"cookies":[...], "storage":{...}}
MCP 包装: "{\"cookies\":[...],\"storage\":{...}}"  ← 外层是 JSON 字符串
```

`_extract_markdown_json_obj` 的 4 个策略都无法解析这种格式 → 返回 None → fallback 路径把 JSON 对象当文档字面量处理 → 按 `;` split 得到空结果 → 报错。

## 用户补充要求

> cookie 和 header 请原始存取，拿到什么存什么，取的时候也是

**含义**：不要对抓取到的数据进行转换/提取/计算，直接存储原始数据，检索时原样返回。

## 修改策略

### 修复 JSON 解析（安全网）

在 `_extract_markdown_json_obj` 中新增策略处理 double-encoded JSON。

### Cookie 原始存取

**之前**：`_GRAB_JS` 采集 → 解析为 `{name: value}` dict → 存储 → 检索时还原为 dict

**之后**：直接取 `document.cookie` 原始字符串 → 存储 → 检索时原样返回

**变更影响**：
- `_GRAB_JS` 简化：不再遍历 cookie 名值对，直接返回 `document.cookie`
- `_grab_cookies_impl`：不再解析 cookie JSON 数组
- 存储/检索：cookies 以原始字符串形式存储和返回

### Auth Token 原始存取

**之前**：`_GRAB_JS` 匹配关键词 → 提取 localStorage/sessionStorage 条目 → 存储为 `[{source, key, value}]`

**之后**：`_GRAB_JS` 返回所有 localStorage/sessionStorage 条目（全量，不筛选关键词）→ 存储时每个条目以 `__auth__ls:{key}` 和 `__auth__ss:{key}` 为键名存储 → 检索时原样返回

### Header 原始存取

**之前**：`_grab_network_headers` 捕获网络请求 → 计算公共 Header（`_compute_common_headers`）→ 存储公共 Header

**之后**：`_grab_network_headers` 捕获网络请求 → 每个请求的 headers 以 `__hdr__:{method}:{url}` 为键名存储 → 不再计算公共 Header → 检索时原样返回所有 raw headers

## 修改文件

| 文件 | 变更 |
|------|------|
| `core/mcp.py` | 简化 `_GRAB_JS`（返回全量原始数据）；新增 JSON 解析策略；简化 `_grab_cookies_impl` 和 `_grab_network_headers` |
| `core/session.py` | `store_site` 和 `get_site` 适配原始存取格式 |
| `server.py` | `_run_grab_task` 适配原始数据格式 |
| `main.py` | `cmd_grab` 输出适配原始格式 |
| `templates/index.html` | 详情弹窗展示适配原始格式 |

## 修改步骤

### 步骤 1：`_extract_markdown_json_obj` 新增策略 2.5

在策略 2 之后，新增策略处理 double-encoded JSON 字符串。

### 步骤 2：简化 `_GRAB_JS`

- cookies：直接返回 `document.cookie` 原始字符串
- storage：返回 localStorage 和 sessionStorage 的**全部**条目（不筛选关键词）

### 步骤 3：简化 `_grab_cookies_impl`

- 不再解析 cookie JSON 数组
- 不再筛选 auth token 关键词
- 直接返回原始 `cookies` 字符串和 `raw_storage` 全量条目

### 步骤 4：简化 `_grab_network_headers`

- 移除 `_compute_common_headers` 调用
- 每个请求的 headers 以原始 `{url, method, headers}` 格式存储

### 步骤 5：适配 `core/session.py`

- `store_site`：cookies 直接存原始字符串；auth tokens 存 `__auth__ls:{key}` / `__auth__ss:{key}` 格式；headers 存 `__hdr__:{method}:{url}` 格式
- `get_site`：原始返回，不做转换

### 步骤 6：适配 `server.py`、`main.py`、`templates/index.html`

- 展示层直接显示原始数据，不做格式化转换

## 验证方式

1. 抓取 `https://chat.deepseek.com/a/chat/s/...` → 正常获取原始 Cookie 字符串 + localStorage/sessionStorage 条目 + 请求 headers
2. 详情弹窗正确显示原始数据
3. 抓取其他站点 → 正常
4. 全部测试通过