---
name: subdomain-matching-for-headers
overview: 修复网络请求头捕获中的域名匹配逻辑，从简单的子串匹配升级为正确的"相同域名 + 子域名"匹配（example.com 应匹配 api.example.com，但不应匹配 notexample.com）。
todos:
  - id: add-helper
    content: 在 core/mcp.py 中新增 _is_same_or_subdomain() 辅助函数，插入到 _parse_network_list_table 之前
    status: pending
  - id: replace-filters
    content: 将 _parse_network_list_table(L273) 和 _grab_network_headers(L479) 中的子串匹配替换为 _is_same_or_subdomain()
    status: pending
    dependencies:
      - add-helper
  - id: add-tests
    content: 在 test_mcp.py 新增 TestIsSameOrSubdomain 测试类，包含 8 个边界 case
    status: pending
    dependencies:
      - add-helper
  - id: run-tests
    content: 运行全量测试确认所有 112 个 case 通过
    status: pending
    dependencies:
      - replace-filters
      - add-tests
---

## 用户需求

解析网络请求时，目标域名的子域名（如 `api.example.com`、`cdn.static.example.com`）应被纳入 Header 分析和存储。当前代码使用 `domain.lower() in url.lower()` 简单子串匹配，存在误匹配（如 `example.com` 会匹配 `notexample.com`）。需要改为精确的域名/子域名判断。

## 核心改动

- 新增 `_is_same_or_subdomain(url_text, domain)` 辅助函数
- 替换 `_parse_network_list_table()` 中的过滤条件
- 替换 `_grab_network_headers()` 中的二次过滤条件
- 新增对应的单元测试

## 技术方案

### 新增辅助函数 `_is_same_or_subdomain(url_text, domain)`

```python
def _is_same_or_subdomain(url_text: str, domain: str) -> bool:
    """检查 URL 文本中的 hostname 是否等于 domain 或是其子域名。

    从 URL 文本中提取 hostname，然后检查：
      - hostname == domain（如 example.com == example.com）
      - hostname.endswith("." + domain)（如 api.example.com 匹配 .example.com）

    不会误匹配：
      - notexample.com 不匹配 example.com
      - example.com.evil.org 不匹配 example.com
    """
    # 尝试从 URL 文本中提取 hostname
    # 支持多种格式：https://host/path, wss://host/path, host/path
    hostname = url_text.lower().strip()
    # 去掉协议前缀
    for prefix in ("https://", "http://", "wss://", "ws://"):
        if hostname.startswith(prefix):
            hostname = hostname[len(prefix):]
            break
    # 去掉路径/端口
    hostname = hostname.split("/")[0].split(":")[0]
    # 去掉可能的引号、空格
    hostname = hostname.strip('"').strip("'").strip()

    dom = domain.lower()
    return hostname == dom or hostname.endswith("." + dom)
```

### 修改点

| 文件 | 位置 | 原代码 | 新代码 |
| --- | --- | --- | --- |
| `core/mcp.py` L273 | `_parse_network_list_table` | `domain.lower() in line.lower()` | `_is_same_or_subdomain(line, domain)` |
| `core/mcp.py` L479 | `_grab_network_headers` | `domain.lower() in detail["url"].lower()` | `_is_same_or_subdomain(detail["url"], domain)` |


### 测试

- 新增 `TestIsSameOrSubdomain` 测试类，覆盖：
- 完全匹配（`example.com == example.com`）
- 一级子域名（`api.example.com`）
- 多级子域名（`cdn.static.example.com`）
- 不应匹配（`notexample.com`、`example.com.evil.org`）
- 路径含域名串（`https://other.com/example.com` 不匹配）
- 带端口（`https://example.com:8080/api` 匹配）
- 更新 `test_parses_matching_domain` 验证子域名行被正确包含