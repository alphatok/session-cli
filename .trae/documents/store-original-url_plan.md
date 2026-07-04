# 记录原始 URL 并用于更新

## 现状

当前流程：用户输入 `https://chat.deepseek.com/a/chat/s/8848c026-...`，服务器提取纯域名 `chat.deepseek.com` 作为 Vault 存储 key，原始 URL 丢失。更新站点时只能使用域名重新抓取，无法回到原始页面。

## 修改方案

### 步骤 1：`core/mcp.py` — 添加 URL_KEY 常量

在 `RAW_COOKIE_KEY` 后添加：
```python
URL_KEY = "__original_url__"
```

### 步骤 2：`core/session.py` — 编码/解码 original_url

**新增辅助函数**：
```python
def _encode_url(original_url: str) -> Dict[str, str]:
    if not original_url:
        return {}
    return {URL_KEY: original_url}

def _decode_url(cookies: Dict[str, str]) -> str:
    return cookies.get(URL_KEY, "")
```

**`store_site`**：增加 `original_url` 参数，编码后合并到 Vault cookies dict 中。

**`list_sites`**：解码并返回 `original_url` 字段。

**`get_site`**：解码并返回 `original_url` 字段。

**`delete_site`**：不需要修改。

### 步骤 3：`server.py` — 传递原始 URL

**`_run_grab_task`**（第 109 行）：
- 当前：`store_domain = domain.strip()...` 提取纯域名
- 修改：将原始 `domain`（完整 URL）传给 `core.store_site(store_domain, data, original_url=domain)`

**`api_refresh_session`**（第 274 行）：
- 当前：`_run_grab_task(task_id, domain)` 使用域名
- 修改：先查 `core.get_site(domain)` 获取 `original_url`，用 `original_url` 或 fallback 到 `domain` 传给 `_run_grab_task`

### 步骤 4：`main.py` — CLI 显示原始 URL

**`cmd_grab`**：传递原始 URL 给 `store_site`。

**`cmd_get`**：显示 `original_url` 字段。

**`cmd_list`**：显示 `original_url` 字段（截断长 URL）。

### 步骤 5：`templates/index.html` — 前端显示原始 URL

**站点列表**：鼠标悬停或域名旁显示原始 URL（fragment 链接）。

**详情弹窗**：显示原始 URL 条目。

### 步骤 6：更新测试 + 验证

- `conftest.py`：fixture 添加 `original_url` 字段
- `test_session.py`：`store_site` 调用添加 `original_url`，断言验证
- `test_server.py`：mock 适配
- `test_mcp.py`：断言适配

## 验证方式

```bash
uv run pytest tests/ -v
```

预期：全部 127 个测试通过。