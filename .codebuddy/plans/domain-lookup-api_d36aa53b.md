---
name: domain-lookup-api
overview: 在 `core/` 包内新增一个独立的 `lookup.py` 模块，提供 `lookup(domain)` 稳定 API，从 Vault 中按域名查询已存储的 cookie + header。支持子域名匹配（如 `api.example.com` → 匹配 `example.com` 的存储），返回精简、类型稳定的 dict。
todos:
  - id: add-query-session
    content: 在 core/session.py 中新增 query_session() 函数：精确匹配 + 子域名回退 + 过期过滤 + 精简返回 dict
    status: completed
  - id: export-query-session
    content: 在 core/__init__.py 中添加 query_session 的 import 和 __all__ 导出
    status: completed
    dependencies:
      - add-query-session
  - id: add-tests
    content: 在 tests/test_session.py 中新增 TestQuerySession 测试类，覆盖精确匹配、子域名回退、未找到、过期过滤、最长匹配优先等场景
    status: completed
    dependencies:
      - add-query-session
  - id: run-all-tests
    content: 运行全量测试确认无回归，验证新函数行为正确
    status: completed
    dependencies:
      - add-tests
---

