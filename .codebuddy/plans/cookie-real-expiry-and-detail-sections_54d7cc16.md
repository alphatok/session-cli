---
name: cookie-real-expiry-and-detail-sections
overview: 1. 从网络请求的 Set-Cookie 响应头解析真实 Cookie 过期时间，替代硬编码的 30 天默认值。2. 详情页面的 section-title 始终显示（即使无数据时显示"暂无"）。
todos:
  - id: parse-set-cookie
    content: 扩展 _parse_network_request_detail 解析 Response Headers 中 set-cookie，返回 set_cookies 列表；新增 _parse_cookie_expiry 辅助函数
    status: completed
  - id: thread-expiry-through-grab
    content: 修改 _grab_network_headers 和 _grab_cookies_impl：收集 cookie_expires_at 并放入返回 dict
    status: completed
    dependencies:
      - parse-set-cookie
  - id: update-store-site
    content: 修改 store_site 和 server.py 透传 cookie_expires_at，优先使用真实过期时间
    status: completed
    dependencies:
      - thread-expiry-through-grab
  - id: update-section-display
    content: 修改 templates/index.html 中 section-title 始终展示，空数据显示"暂无"
    status: completed
  - id: update-tests-and-verify
    content: 更新测试用例并运行全量测试验证
    status: completed
    dependencies:
      - parse-set-cookie
      - update-store-site
      - update-section-display
---

## 需求1：Cookie 真实过期时间

当前 `store_site` 写死 `expires_at = utcnow() + timedelta(days=30)`。需要改为：从网络请求的 Response Headers 中解析 `Set-Cookie` 头中的 `expires=` 或 `max-age=`，取最早过期时间作为存储的过期时间。若无 Set-Cookie 则回退到默认 30 天。

涉及数据流：`_parse_network_request_detail` → `_grab_network_headers` → `_grab_cookies_impl` → `store_site` → `server.py`

## 需求2：detail-section-title 默认展示

当前详情面板中「认证凭据」「公共 Request Headers」「原始请求列表」「关联域名」四个 section-title 仅在数据非空时渲染。改为始终显示标题，无数据时显示"暂无"占位文本。

## Tech Stack

- Python 3.13 + 现有 mcp.py / session.py / server.py
- HTML/JS 前端 template

## 实现方案

### 需求1：Cookie 真实过期时间

**核心思路**：在 `_parse_network_request_detail` 中扩展解析 Response Headers 区块，收集 `set-cookie` 行；在 `_grab_network_headers` 中新增 `_parse_cookie_expiry()` 解析最早过期时间，通过返回值链传递到 `store_site`。

**解析 Set-Cookie 格式**：

```
- set-cookie:session=abc; Expires=Sat, 04 Jul 2026 16:25:38 GMT; Max-Age=3600
```

提取 `expires=` 后的 HTTP-date，或 `max-age=` 后的秒数计算出过期时间。

**关键设计决策**：

- 取所有 Set-Cookie 中**最早过期的**作为存储过期时间（最保守策略）
- 若没有任何 Set-Cookie 或解析失败，回退到 30 天默认值
- `from datetime import datetime, timedelta, timezone` 需要新增导入

### 需求2：detail-section-title 默认展示

四组 section-title 从条件渲染改为始终渲染，空数据时用淡色"暂无"文本占位。

## 需要修改的文件

### core/mcp.py

- 新增 `from datetime import datetime, timedelta, timezone` 导入
- `_parse_network_request_detail()` 扩展返回值：增加 `set_cookies: [str]` 字段，解析 Response Headers 中的 `set-cookie` 行
- 新增 `_parse_cookie_expiry(set_cookies: list[str]) -> Optional[datetime]` 辅助函数
- `_grab_network_headers()` 返回值从 `tuple[3]` 改为 `tuple[4]`：`(common_headers, raw_requests, related_domains, cookie_expires_at)`
- `_grab_cookies_impl()` 接收 `cookie_expires_at` 并加入返回 dict

### core/session.py

- `store_site()` 新增 `cookie_expires_at: Optional[datetime] = None` 参数，优先使用

### server.py

- `_run_grab_task()` 提取 `cookie_expires_at` 并透传 `store_site`

### templates/index.html

- 四组 section-title 改为始终渲染，空数据时显示"暂无"

### tests/conftest.py

- 新增 fixture `sample_network_detail_with_setcookie` 包含 Set-Cookie 样例

### tests/test_mcp.py

- 新增 `test_parses_set_cookie_from_response` 测试
- 新增 `test_parse_cookie_expiry` 测试

### tests/test_session.py

- 更新 `test_store_with_headers` 验证 cookie_expires_at 参数