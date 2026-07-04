# 恢复公共 Request Headers 展示

## 现状

`_compute_common_headers` 函数仍在（[mcp.py#L507](file:///d:/github/session-cli/core/mcp.py#L507)，统计跨请求不变的 Header 键值对），但 `_grab_network_headers` 返回 `{}, raw_requests, related_domains` 始终丢弃了计算结果。

前端和 CLI 已有展示逻辑，只是 `headers` 始终为空所以不显示。

## 修改

### `core/mcp.py` 第 646 行

```python
# 旧
return {}, raw_requests, related_domains

# 新
return _compute_common_headers(raw_requests), raw_requests, related_domains
```

前端"公共 Request Headers"区域和 CLI `cmd_get` 已有展示代码，无需额外修改。

## 验证

```bash
uv run pytest tests/ -v
```