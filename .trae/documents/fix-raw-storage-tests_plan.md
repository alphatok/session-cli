# 修复原始存取后的测试失败

## 当前状态

代码修改已完成（步骤 1-6），但 12 个测试失败。需要修复：
1. 测试 fixture 适配新的原始存取格式
2. 测试 body 中的断言适配新格式
3. 修复 `list_sites` 中的 `cookie_count` 计算 bug

## 根本原因

`_encode_auth_tokens` 和 `_decode_auth_tokens` 的签名/行为已变更：
- `_encode_auth_tokens(cookies: str, auth_tokens: list)` — cookies 是原始字符串
- `_decode_auth_tokens(cookies: dict)` → `(raw_cookie: str, auth_tokens: list)` — 返回原始字符串
- `store_site` 中 `data["cookies"]` 是字符串
- `get_site` 中 `cookies` 字段是字符串
- `_grab_cookies_impl` 中 `cookies` 是字符串
- `_GRAB_JS` 返回 `{"cookie": "...", "localStorage": {...}, "sessionStorage": {...}}`

测试用的 fixture 和断言仍使用旧格式（dict cookies），导致失败。

## 修改步骤

### 步骤 1：修复 `list_sites` 中的 `cookie_count` bug

**文件**: `core/session.py` 第 187 行

**问题**: `pure_cookies` 现在是字符串（raw_cookie），`len(pure_cookies)` 计数的是字符数而非 cookie 数量。

**修改**: 
```python
# 旧
"cookie_count": len(pure_cookies),
# 新
"cookie_count": pure_cookies.count(";") + 1 if pure_cookies else 0,
```

### 步骤 2：更新 `conftest.py` 测试 fixtures

**文件**: `tests/conftest.py`

#### 2.1 `sample_mcp_grab_json`（第 112 行）
旧格式 `{"cookies":[...], "storage":{...}}` → 新格式 `{"cookie":"...", "localStorage":{...}, "sessionStorage":{...}}`：
```python
return (
    "Script ran on page and returned:\n"
    "```json\n"
    '{"cookie":"token=abc123; session=xyz789",'
    '"localStorage":{"auth_token":"Bearer eyJhbGciOiJIUzI1NiJ9.xxx","refresh_token":"rt_abc123"},'
    '"sessionStorage":{}}'
    "\n```"
)
```

#### 2.2 `sample_grab_enriched`（第 125 行）
`"cookies"` 从 dict 改为 string：
```python
return {
    "cookies": "token=abc123; session=xyz789",
    "auth_tokens": [
        {"source": "localStorage", "key": "auth_token", "value": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx"},
        {"source": "localStorage", "key": "refresh_token", "value": "rt_abc123"},
    ],
}
```

#### 2.3 `sample_auth_encoded_cookies`（第 137 行）
添加 `__raw__cookie` 键，移除纯 cookie 的 name-value 键：
```python
return {
    "__raw__cookie": "token=abc123; session=xyz789",
    "__auth__ls:auth_token": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx",
    "__auth__ls:refresh_token": "rt_abc123",
    "__auth__ss:session_id": "sess_456",
}
```

#### 2.4 `sample_grab_with_headers`（第 210 行）
`"cookies"` 从 dict 改为 string：
```python
return {
    "cookies": "token=abc123; session=xyz789",
    ...
}
```

#### 2.5 `sample_header_encoded_cookies`（第 249 行）
添加 `__raw__cookie` 键，移除 `"token"` 键：
```python
return {
    "__raw__cookie": "token=abc123",
    "__hdr__Authorization": "Bearer xxx",
    "__hdr__User-Agent": "Mozilla/5.0",
    "__raw__requests": json.dumps(raw),
}
```

### 步骤 3：更新 `test_mcp.py`

**文件**: `tests/test_mcp.py`

#### 3.1 `test_full_grab_flow`（第 238 行）
更新 `cookie_text` 为新格式：
```python
cookie_text = (
    'Script ran on page and returned:\n'
    '```json\n'
    '{"cookie":"token=abc; uid=123",'
    '"localStorage":{"auth_key":"secret123"},"sessionStorage":{}}'
    '\n```'
)
```

更新断言（第 273-277 行）：
```python
# 旧
assert len(result["cookies"]) == 2
assert result["cookies"]["token"] == "abc"
# 新
assert result["cookies"] == "token=abc; uid=123"
```

#### 3.2 `TestExtractMarkdownJsonObj` 类
`test_extracts_json_object` 和 `test_parses_auth_tokens` 使用 `sample_mcp_grab_json`，fixture 更新后断言需适配新格式：
- `result["cookies"]` → `result["cookie"]`（字符串）
- `result["storage"]` → `result["localStorage"]` / `result["sessionStorage"]`

`test_empty_storage` 内联数据需更新为新格式。

`test_falls_back_to_regex_pattern` 内联数据需更新为新格式。

### 步骤 4：更新 `test_server.py`

**文件**: `tests/test_server.py`

#### 4.1 `test_success_flow`（第 155 行）
```python
# 旧
mock_grab.return_value = {
    "cookies": {"token": "abc"},
    ...
}
# 新
mock_grab.return_value = {
    "cookies": "token=abc",
    ...
}
```

#### 4.2 `test_empty_cookies`（第 179 行）
```python
# 旧
"cookies": {},
# 新
"cookies": "",
```

### 步骤 5：更新 `test_session.py`

**文件**: `tests/test_session.py`

#### 5.1 `TestListSites.test_returns_formatted_list`（第 33 行）
`cookie_count` 断言现在正确反映 semicolon 计数。`s1.cookies` 中 `__raw__cookie` 为 `"token=abc123; session=xyz789"`，有 1 个分号 → 2 个 cookie。断言保持 `== 2`。

#### 5.2 `TestGetSite.test_returns_site_detail`（第 62 行）
```python
# 旧
s.cookies = {"token": "abc", "uid": "123"}
# 新
s.cookies = {"__raw__cookie": "token=abc; uid=123"}
```

```python
# 旧
assert result["cookie_count"] == 2
assert result["cookies"]["token"] == "abc"
# 新
assert result["cookie_count"] == 2
assert result["cookies"] == "token=abc; uid=123"
```

#### 5.3 `TestStoreSite.test_stores_with_30_day_expiry`（第 104 行）
```python
# 旧
data = {"cookies": {"key": "val"}, ...}
# 新
data = {"cookies": "key=val", ...}
```
`cookie_count` 断言从 `1` 保持不变。

#### 5.4 `TestStoreSite.test_stores_with_auth_tokens`（第 115 行）
使用 `sample_grab_enriched`，fixture 更新后：
- `cookie_count` 断言：`"token=abc123; session=xyz789"` 中 1 个分号 → 2 个 cookie
- `stored_cookies["token"]` → `stored_cookies["__raw__cookie"]`

#### 5.5 `TestAuthTokenEncodeDecode` 类（第 158 行）
`_encode_auth_tokens` 现在签名是 `(cookies: str, auth_tokens: list)`，cookies 是字符串。

`test_encode_merges_auth_tokens`：
```python
# 旧
cookies = {"a": "1", "b": "2"}
result = _encode_auth_tokens(cookies, auth)
assert result["a"] == "1"
assert result["b"] == "2"
# 新
cookies = "a=1; b=2"
result = _encode_auth_tokens(cookies, auth)
assert result["__raw__cookie"] == "a=1; b=2"
```

`test_encode_does_not_mutate_original`：
```python
# 旧
cookies = {"c": "3"}
# 新
cookies = "c=3"
```

`test_decode_separates_auth_from_cookies`：`_decode_auth_tokens` 现在返回 `(str, list)`。
```python
# 旧
pure, auth = _decode_auth_tokens(sample_auth_encoded_cookies)
assert len(pure) == 2
assert pure["token"] == "abc123"
assert pure["session"] == "xyz789"
# 新
raw_cookie, auth = _decode_auth_tokens(sample_auth_encoded_cookies)
assert raw_cookie == "token=abc123; session=xyz789"
```

`test_decode_empty_auth`：
```python
# 旧
pure, auth = _decode_auth_tokens({"a": "1", "b": "2"})
assert pure == {"a": "1", "b": "2"}
# 新
raw_cookie, auth = _decode_auth_tokens({"__raw__cookie": "a=1; b=2"})
assert raw_cookie == "a=1; b=2"
```

`test_decode_all_auth_no_cookies`：
```python
# 旧
pure, auth = _decode_auth_tokens({"__auth__ls:t1": "v1", "__auth__ss:t2": "v2"})
assert pure == {}
# 新
raw_cookie, auth = _decode_auth_tokens({"__auth__ls:t1": "v1", "__auth__ss:t2": "v2"})
assert raw_cookie == ""
```

`test_roundtrip_encode_decode`：使用 `sample_grab_enriched`，fixture 更新后：
```python
# 旧
encoded = _encode_auth_tokens(
    sample_grab_enriched["cookies"],
    sample_grab_enriched["auth_tokens"],
)
pure, auth = _decode_auth_tokens(encoded)
assert pure == sample_grab_enriched["cookies"]
# 新
raw_cookie, auth = _decode_auth_tokens(encoded)
assert raw_cookie == sample_grab_enriched["cookies"]
```

#### 5.6 `TestStoreSiteWithHeaders.test_store_with_headers`（第 298 行）
使用 `sample_grab_with_headers`，fixture 更新后 `cookie_count` 断言：`"token=abc123; session=xyz789"` → 2 个 cookie。

#### 5.7 `TestStoreSiteWithHeaders.test_get_site_with_headers`（第 322 行）
`s.cookies` 添加 `__raw__cookie` 键：
```python
s.cookies = {
    "__raw__cookie": "token=abc",
    "__hdr__Authorization": "Bearer xxx",
    "__hdr__Accept": "application/json",
    "__raw__requests": raw,
}
```

#### 5.8 `TestStoreSiteWithHeaders.test_backward_compatible_no_headers`（第 351 行）
`s.cookies` 添加 `__raw__cookie` 键：
```python
s.cookies = {"__raw__cookie": "token=abc; uid=123"}
```

#### 5.9 `TestStoreSiteWithRelated.test_store_with_related`（第 422 行）
```python
# 旧
data = {"cookies": {"token": "abc"}, ...}
# 新
data = {"cookies": "token=abc", ...}
```

## 验证方式

```bash
uv run pytest tests/ -v
```

预期：全部 127 个测试通过。