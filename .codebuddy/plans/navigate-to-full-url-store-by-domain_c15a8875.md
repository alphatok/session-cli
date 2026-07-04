---
name: navigate-to-full-url-store-by-domain
overview: 修改 _grab_cookies_impl 增加 url 参数用于导航到用户提供的完整 URL，domain 参数仅用于存储/解析/匹配。涉及 mcp.py、mcp_manager.py、server.py 等文件的修改。
todos:
  - id: modify-grab-cookies-impl
    content: 修改 core/mcp.py 中 _grab_cookies_impl 增加 url 可选参数，导航时使用 url（None 时回退 https://{domain}）
    status: completed
  - id: modify-grab-cookies-entry
    content: 修改 core/mcp.py 中 grab_cookies() 入口：保存原始输入、提取 domain、构建导航 URL，传入 _grab_cookies_impl
    status: completed
    dependencies:
      - modify-grab-cookies-impl
  - id: modify-grab-cookies-managed
    content: 修改 core/mcp_manager.py 中 grab_cookies_managed() 入口：同样分离 url/domain，传入 _grab_cookies_impl
    status: completed
    dependencies:
      - modify-grab-cookies-impl
  - id: fix-server-store-domain
    content: 修改 server.py 中 _run_grab_task：提取纯 domain 用于 store_site，原始输入传给 grab_cookies_managed
    status: completed
    dependencies:
      - modify-grab-cookies-managed
  - id: update-frontend-placeholder
    content: 更新 templates/index.html 输入框 placeholder 为"输入域名或 URL"
    status: completed
  - id: verify-tests
    content: 运行测试验证所有修改向后兼容，纯 domain 输入行为不变
    status: completed
    dependencies:
      - modify-grab-cookies-entry
      - modify-grab-cookies-managed
      - fix-server-store-domain
---

## 用户需求

用户提供完整 URL（如 `https://chat.deepseek.com/a/chat/s/8848c026-39ff-4952-b732-e1815973925b`）时：

- **navigate_page 导航**：使用用户提供的完整 URL（保留路径参数）
- **存储/解析/匹配**：只使用从 URL 中提取的纯 domain（如 `chat.deepseek.com`）

## 核心功能

1. `_grab_cookies_impl` 新增 `url` 可选参数，导航时使用完整 URL，domain 保持用于页面匹配、Header 过滤、Cookie 采集
2. `grab_cookies()` / `grab_cookies_managed()` 入口处分离原始输入和纯 domain，一并传入 impl
3. `server.py:_run_grab_task` 提取纯 domain 用于 Vault 存储 key，原始输入传递给抓取函数
4. 前端输入框 placeholder 更新，提示支持完整 URL 输入
5. 纯 domain 输入（如 `test.example.com`）保持向后兼容，自动补全为 `https://{domain}`

## 技术方案

### 实现方式

在 `_grab_cookies_impl` 函数签名中新增可选参数 `url: str | None = None`，作为 navigate_page 的导航目标。调用方在 `grab_cookies()` / `grab_cookies_managed()` 入口处完成 URL→domain 的提取和导航 URL 的构建，然后一并传入。

### 关键设计决策

- **url 参数默认 None**：向后兼容，None 时回退到 `f"https://{domain}"`
- **domain 用途不变**：页面列表匹配（`if domain in line`）、Header 域名过滤（`_is_same_or_subdomain`）、Cookie JS 采集均在当前 domain 上下文中执行
- **入口统一提取**：domain 提取逻辑（strip 协议、端口、路径）仍在 `grab_cookies()` / `grab_cookies_managed()` 入口完成，保证 domain 参数语义一致
- **server.py 存储修正**：`_run_grab_task` 中 `store_site(domain, data)` 的 domain 参数当前可能是完整 URL，需提取纯 domain

### 数据流

```
用户输入 "https://chat.deepseek.com/a/chat/s/xxx"
  → grab_cookies(raw_input):
      domain = "chat.deepseek.com" (提取)
      navigate_url = "https://chat.deepseek.com/a/chat/s/xxx" (保留)
      → _grab_cookies_impl(proc, domain, url=navigate_url):
          navigate_page(url=navigate_url)  # 导航到完整 URL
          页面匹配: domain in line          # 用纯 domain
          Header 过滤: is_same_or_subdomain(line, domain)  # 用纯 domain
  → store_site(domain, data)  # Vault key 为纯 domain
```

### 修改范围

- `core/mcp.py`：`_grab_cookies_impl` 增参，`grab_cookies` 入口重构
- `core/mcp_manager.py`：`grab_cookies_managed` 入口重构
- `server.py`：`_run_grab_task` 提取 domain 用于存储
- `templates/index.html`：placeholder 文案更新
- 测试文件：无需大幅修改（现有测试传纯 domain，向后兼容）