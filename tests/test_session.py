"""core/session.py 测试 — CRUD 操作 + grab_cookies 委托。"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock, patch

import pytest

from core.session import (
    list_sites, get_site, store_site, delete_site, query_session,
    _encode_auth_tokens, _decode_auth_tokens,
    _encode_headers, _decode_headers,
    _encode_related, _decode_related,
    _encode_url, _decode_url,
)


class TestListSites:
    """列出站点（Bug #1 修复验证：不再 close vault）。"""

    @patch("core.session.get_vault")
    def test_returns_formatted_list(self, mock_get_vault, sample_session_rows):
        """返回格式化的站点列表，且不调用 close()。"""
        v = MagicMock()
        v.list_sessions.return_value = sample_session_rows
        mock_get_vault.return_value = v

        result = list_sites()

        assert len(result) == 2
        assert result[0]["domain"] == "example.com"
        # s1 has 2 pure cookies + 1 __auth__ entry → pure count = 2
        assert result[0]["cookie_count"] == 2
        assert result[0]["auth_token_count"] == 1  # 1 encoded auth token
        assert result[0]["expired"] is False
        assert result[1]["domain"] == "test.org"
        assert result[1]["expired"] is True  # 已过期

        # Bug #1: 不应调用 close()
        v.close.assert_not_called()

    @patch("core.session.get_vault")
    def test_empty_list(self, mock_get_vault):
        """无站点时返回空列表。"""
        v = MagicMock()
        v.list_sessions.return_value = []
        mock_get_vault.return_value = v

        result = list_sites()
        assert result == []


class TestGetSite:
    """获取站点详情。"""

    @patch("core.session.get_vault")
    def test_returns_site_detail(self, mock_get_vault):
        """返回站点完整信息。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "example.com"
        s.cookies = {"__raw__cookie": "token=abc; uid=123"}
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = get_site("example.com")
        assert result["domain"] == "example.com"
        assert result["cookie_count"] == 2
        assert result["cookies"] == "token=abc; uid=123"
        v.close.assert_not_called()

    @patch("core.session.get_vault")
    def test_not_found(self, mock_get_vault):
        """不存在的站点返回 None。"""
        v = MagicMock()
        v.get_session.return_value = None
        mock_get_vault.return_value = v

        result = get_site("nonexistent.com")
        assert result is None


class TestStoreSite:
    """存储站点。"""

    @patch("core.session.get_vault")
    def test_stores_with_30_day_expiry(self, mock_get_vault):
        """默认 30 天过期（v2：接受 enriched dict）。"""
        from datetime import datetime, UTC
        v = MagicMock()

        def capture_store(**kwargs):
            s = MagicMock()
            s.domain = kwargs["domain"]
            return s

        v.store_session.side_effect = capture_store
        mock_get_vault.return_value = v

        data = {"cookies": "key=val", "auth_tokens": [], "headers": {}, "raw_requests": []}
        result = store_site("test.com", data)
        assert result["domain"] == "test.com"
        assert result["cookie_count"] == 1
        assert result["header_count"] == 0

        call_kwargs = v.store_session.call_args[1]
        assert "expires_at" in call_kwargs
        v.close.assert_not_called()

    @patch("core.session.get_vault")
    def test_stores_with_auth_tokens(self, mock_get_vault, sample_grab_enriched):
        """认证凭据以 __auth__ 前缀编码存入。"""
        v = MagicMock()
        stored_cookies = {}

        def capture_store(**kwargs):
            nonlocal stored_cookies
            stored_cookies = dict(kwargs["cookies"])

        v.store_session.side_effect = capture_store
        mock_get_vault.return_value = v

        result = store_site("example.com", sample_grab_enriched)
        assert result["cookie_count"] == 2
        assert result["auth_token_count"] == 2

        # 验证编码后的 cookies 包含 __auth__ 前缀
        assert "__auth__ls:auth_token" in stored_cookies
        assert "__auth__ls:refresh_token" in stored_cookies
        assert stored_cookies["__raw__cookie"] == "token=abc123; session=xyz789"


class TestDeleteSite:
    """删除站点。"""

    @patch("core.session.get_vault")
    def test_delete_existing(self, mock_get_vault):
        v = MagicMock()
        v.delete_session.return_value = True
        mock_get_vault.return_value = v

        assert delete_site("test.com") is True
        v.close.assert_not_called()

    @patch("core.session.get_vault")
    def test_delete_nonexistent(self, mock_get_vault):
        v = MagicMock()
        v.delete_session.return_value = False
        mock_get_vault.return_value = v

        assert delete_site("nope.com") is False


class TestAuthTokenEncodeDecode:
    """认证凭据的 __auth__ 编码/解码（v2 新增）。"""

    def test_encode_merges_auth_tokens(self):
        """编码后 cookies dict 包含原始 cookie + __auth__ 前缀凭据。"""
        cookies = "a=1; b=2"
        auth = [
            {"source": "localStorage", "key": "access_token", "value": "xxx"},
            {"source": "sessionStorage", "key": "sess_id", "value": "yyy"},
        ]
        result = _encode_auth_tokens(cookies, auth)

        assert result["__raw__cookie"] == "a=1; b=2"
        assert result["__auth__ls:access_token"] == "xxx"
        assert result["__auth__ss:sess_id"] == "yyy"
        assert len(result) == 3

    def test_encode_does_not_mutate_original(self):
        """编码不修改原始 dict。"""
        cookies = "c=3"
        auth = [{"source": "localStorage", "key": "t", "value": "v"}]
        _encode_auth_tokens(cookies, auth)
        assert cookies == "c=3"  # 原始字符串未被修改

    def test_decode_separates_auth_from_cookies(self, sample_auth_encoded_cookies):
        """解码将 __auth__ 条目分离为 auth_tokens。"""
        raw_cookie, auth = _decode_auth_tokens(sample_auth_encoded_cookies)

        assert raw_cookie == "token=abc123; session=xyz789"

        assert len(auth) == 3
        sources = {t["source"] for t in auth}
        assert "localStorage" in sources
        assert "sessionStorage" in sources

        # 验证 localStorage 凭据
        ls_tokens = [t for t in auth if t["source"] == "localStorage"]
        assert len(ls_tokens) == 2
        ls_keys = {t["key"] for t in ls_tokens}
        assert "auth_token" in ls_keys
        assert "refresh_token" in ls_keys

    def test_decode_empty_auth(self):
        """无 __auth__ 条目的 cookies 返回空 auth_tokens。"""
        raw_cookie, auth = _decode_auth_tokens({"__raw__cookie": "a=1; b=2"})
        assert raw_cookie == "a=1; b=2"
        assert auth == []

    def test_decode_all_auth_no_cookies(self):
        """全部是 __auth__ 条目时 raw_cookie 为空。"""
        raw_cookie, auth = _decode_auth_tokens({
            "__auth__ls:t1": "v1",
            "__auth__ss:t2": "v2",
        })
        assert raw_cookie == ""
        assert len(auth) == 2

    def test_roundtrip_encode_decode(self, sample_grab_enriched):
        """编码 → 解码 往返保持凭据完整性。"""
        encoded = _encode_auth_tokens(
            sample_grab_enriched["cookies"],
            sample_grab_enriched["auth_tokens"],
        )
        raw_cookie, auth = _decode_auth_tokens(encoded)

        assert raw_cookie == sample_grab_enriched["cookies"]
        assert len(auth) == len(sample_grab_enriched["auth_tokens"])


# ── 原始 URL 编解码测试 ──────────────────────────────────────────


class TestUrlEncodeDecode:
    """原始 URL 的 __original_url__ 编码/解码。"""

    def test_encode_url(self):
        encoded = _encode_url("https://chat.deepseek.com/a/chat/s/xxx")
        assert encoded["__original_url__"] == "https://chat.deepseek.com/a/chat/s/xxx"

    def test_encode_url_empty(self):
        assert _encode_url("") == {}
        assert _encode_url(None) == {}

    def test_decode_url(self):
        dat = {"__original_url__": "https://example.com/path"}
        assert _decode_url(dat) == "https://example.com/path"

    def test_decode_url_absent(self):
        assert _decode_url({}) == ""
        assert _decode_url({"token": "abc"}) == ""

    @patch("core.session.get_vault")
    def test_store_site_with_url(self, mock_get_vault):
        """store_site 传入 original_url 后编码到 Vault cookies 中。"""
        v = MagicMock()
        stored_all = {}

        def capture_store(**kwargs):
            nonlocal stored_all
            stored_all = dict(kwargs["cookies"])

        v.store_session.side_effect = capture_store
        mock_get_vault.return_value = v

        data = {"cookies": "token=abc", "auth_tokens": [], "headers": {}, "raw_requests": []}
        result = store_site("example.com", data, original_url="https://example.com/path")
        assert result["original_url"] == "https://example.com/path"
        assert stored_all["__original_url__"] == "https://example.com/path"

    @patch("core.session.get_vault")
    def test_get_site_returns_original_url(self, mock_get_vault):
        """get_site 返回原始 URL。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "example.com"
        s.cookies = {
            "__raw__cookie": "token=abc",
            "__original_url__": "https://example.com/some/path",
        }
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = get_site("example.com")
        assert result["original_url"] == "https://example.com/some/path"


# ── Header 编解码测试 ──────────────────────────────────────────


class TestHeaderEncodeDecode:
    """公共 Header 和 raw_requests 的 __hdr__ 编码/解码。"""

    def test_encode_headers(self):
        """Header 以 __hdr__ 前缀编码。"""
        headers = {"Authorization": "Bearer xxx", "User-Agent": "Mozilla/5.0"}
        encoded = _encode_headers(headers, [])
        assert encoded["__hdr__Authorization"] == "Bearer xxx"
        assert encoded["__hdr__User-Agent"] == "Mozilla/5.0"
        assert "__raw__requests" not in encoded

    def test_encode_raw_requests(self):
        """raw_requests 编码为 JSON blob（单键）。"""
        raw = [
            {"url": "https://example.com/api", "method": "GET",
             "headers": {"Authorization": "Bearer xxx"}},
        ]
        encoded = _encode_headers({}, raw)
        assert "__raw__requests" in encoded
        import json
        decoded_raw = json.loads(encoded["__raw__requests"])
        assert decoded_raw == raw

    def test_encode_both(self):
        headers = {"Authorization": "Bearer xxx"}
        raw = [{"url": "a", "method": "GET", "headers": {}}]
        encoded = _encode_headers(headers, raw)
        assert "__hdr__Authorization" in encoded
        assert "__raw__requests" in encoded

    def test_decode_headers(self, sample_header_encoded_cookies):
        """解码分离出 headers 和 raw_requests。"""
        headers, raw = _decode_headers(sample_header_encoded_cookies)
        assert headers["Authorization"] == "Bearer xxx"
        assert headers["User-Agent"] == "Mozilla/5.0"
        assert len(raw) == 1
        assert raw[0]["url"] == "https://example.com/api/me"

    def test_decode_empty(self):
        """无 __hdr__ 前缀时返回空。"""
        headers, raw = _decode_headers({"a": "1", "b": "2"})
        assert headers == {}
        assert raw == []

    def test_decode_invalid_raw_json(self):
        """损坏的 raw_requests JSON 不崩溃。"""
        dat = {"__raw__requests": "not valid json {{{"}
        headers, raw = _decode_headers(dat)
        assert raw == []

    def test_roundtrip(self, sample_grab_with_headers):
        """Header 编解码往返保持完整性。"""
        encoded = _encode_headers(
            sample_grab_with_headers["headers"],
            sample_grab_with_headers["raw_requests"],
        )
        headers, raw = _decode_headers(encoded)
        assert headers == sample_grab_with_headers["headers"]
        assert raw == sample_grab_with_headers["raw_requests"]


class TestStoreSiteWithHeaders:
    """store_site / get_site 支持 headers + raw_requests。"""

    @patch("core.session.get_vault")
    def test_store_with_headers(self, mock_get_vault, sample_grab_with_headers):
        """存储含 headers + raw_requests 的数据。"""
        v = MagicMock()
        stored_all = {}

        def capture_store(**kwargs):
            nonlocal stored_all
            stored_all = dict(kwargs["cookies"])

        v.store_session.side_effect = capture_store
        mock_get_vault.return_value = v

        result = store_site("example.com", sample_grab_with_headers)
        assert result["cookie_count"] == 2
        assert result["auth_token_count"] == 1
        assert result["header_count"] == 3
        assert result["raw_request_count"] == 2

        # 验证编码：Vault 中应有 __hdr__ 前缀键
        assert "__hdr__Authorization" in stored_all
        assert "__hdr__User-Agent" in stored_all
        assert "__raw__requests" in stored_all

    @patch("core.session.get_vault")
    def test_get_site_with_headers(self, mock_get_vault):
        """从 Vault 读取含 headers 的站点详情。"""
        import json
        raw = json.dumps([
            {"url": "https://example.com/api", "method": "GET",
             "headers": {"Authorization": "Bearer xxx"}},
        ])
        s = MagicMock()
        s.domain = "example.com"
        s.cookies = {
            "__raw__cookie": "token=abc",
            "__hdr__Authorization": "Bearer xxx",
            "__hdr__Accept": "application/json",
            "__raw__requests": raw,
        }
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = get_site("example.com")
        assert result["headers"] == {"Authorization": "Bearer xxx", "Accept": "application/json"}
        assert result["header_count"] == 2
        assert result["raw_request_count"] == 1
        assert result["raw_requests"][0]["url"] == "https://example.com/api"

    @patch("core.session.get_vault")
    def test_backward_compatible_no_headers(self, mock_get_vault):
        """旧数据（无 headers）读取时不崩溃，返回空。"""
        s = MagicMock()
        s.domain = "old.com"
        s.cookies = {"__raw__cookie": "token=abc; uid=123"}
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = get_site("old.com")
        assert result["headers"] == {}
        assert result["header_count"] == 0
        assert result["raw_requests"] == []
        assert result["raw_request_count"] == 0
        assert result["related_domains"] == []
        assert result["related_domain_count"] == 0


# ── 关联域名编解码测试 ──────────────────────────────────────────


class TestRelatedDomainsEncodeDecode:
    """关联域名的 __rel__ 编码/解码。"""

    def test_encode_related(self):
        related = ["api.example.com", "cdn.cloudflare.com", "google.com"]
        encoded = _encode_related(related)
        assert "__rel__domains" in encoded
        import json
        decoded = json.loads(encoded["__rel__domains"])
        assert "api.example.com" in decoded
        assert "google.com" in decoded

    def test_encode_deduplicates(self):
        related = ["api.example.com", "api.example.com", "google.com"]
        encoded = _encode_related(related)
        import json
        decoded = json.loads(encoded["__rel__domains"])
        assert len(decoded) == 2

    def test_encode_empty(self):
        assert _encode_related([]) == {}
        assert _encode_related([""]) == {}

    def test_decode_related(self):
        import json
        dat = {"__rel__domains": json.dumps(["a.com", "b.com"])}
        result = _decode_related(dat)
        assert result == ["a.com", "b.com"]

    def test_decode_empty(self):
        assert _decode_related({}) == []
        assert _decode_related({"token": "abc"}) == []

    def test_decode_invalid_json(self):
        dat = {"__rel__domains": "not valid json {{{"}
        assert _decode_related(dat) == []

    def test_roundtrip(self):
        related = ["api.example.com", "cdn.cloudflare.com", "google.com"]
        encoded = _encode_related(related)
        decoded = _decode_related(encoded)
        assert decoded == sorted(related)


class TestStoreSiteWithRelated:
    """store_site / get_site 支持 related_domains。"""

    @patch("core.session.get_vault")
    def test_store_with_related(self, mock_get_vault):
        """存储含 related_domains 的数据。"""
        v = MagicMock()
        stored_all = {}

        def capture_store(**kwargs):
            nonlocal stored_all
            stored_all = dict(kwargs["cookies"])

        v.store_session.side_effect = capture_store
        mock_get_vault.return_value = v

        data = {
            "cookies": "token=abc",
            "auth_tokens": [],
            "headers": {},
            "raw_requests": [],
            "related_domains": ["api.example.com", "cdn.cloudflare.com"],
        }
        result = store_site("example.com", data)
        assert result["related_domain_count"] == 2
        assert "__rel__domains" in stored_all


# ── query_session() 测试 ────────────────────────────────────────


class TestQuerySession:
    """query_session() — 稳定程序化查询接口（精确匹配 + 子域名回退 + 过期过滤）。"""

    @patch("core.session.get_vault")
    def test_exact_match(self, mock_get_vault):
        """精确匹配：直接命中存储域名。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "example.com"
        s.cookies = {
            "__raw__cookie": "token=abc; uid=123",
            "__hdr__Authorization": "Bearer xxx",
        }
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = query_session("example.com")

        assert result["found"] is True
        assert result["domain"] == "example.com"
        assert result["matched_by"] == "exact"
        assert result["cookies"] == "token=abc; uid=123"
        assert result["headers"] == {"Authorization": "Bearer xxx"}
        assert result["expired"] is False

    @patch("core.session.get_vault")
    def test_exact_match_cleans_url(self, mock_get_vault):
        """传入完整 URL 时自动清洗为纯域名再匹配。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "example.com"
        s.cookies = {"__raw__cookie": "token=abc"}
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = query_session("https://example.com/path/to/page")

        assert result["found"] is True
        assert result["domain"] == "example.com"
        assert result["matched_by"] == "exact"

    @patch("core.session.get_vault")
    def test_subdomain_match(self, mock_get_vault):
        """子域名回退：查 api.example.com → 命中 example.com。"""
        from datetime import datetime, UTC

        # 精确匹配返回 None
        parent_s = MagicMock()
        parent_s.domain = "example.com"
        parent_s.cookies = {"__raw__cookie": "token=main"}
        parent_s.created_at = datetime(2026, 1, 1, 12, 0)
        parent_s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = None  # 精确匹配失败
        v.list_sessions.return_value = [parent_s]
        mock_get_vault.return_value = v

        result = query_session("api.example.com")

        assert result["found"] is True
        assert result["domain"] == "example.com"
        assert result["matched_by"] == "subdomain"
        assert result["cookies"] == "token=main"

    @patch("core.session.get_vault")
    def test_subdomain_match_longest_priority(self, mock_get_vault):
        """子域名回退：多个父域名时取最长匹配（最精准）。"""
        from datetime import datetime, UTC

        s_co = MagicMock()
        s_co.domain = "service.example.com"
        s_co.cookies = {"__raw__cookie": "token=service"}
        s_co.created_at = datetime(2026, 1, 1, 12, 0)
        s_co.expires_at = datetime(2026, 12, 31, 12, 0)

        s_ex = MagicMock()
        s_ex.domain = "example.com"
        s_ex.cookies = {"__raw__cookie": "token=root"}
        s_ex.created_at = datetime(2026, 1, 1, 12, 0)
        s_ex.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = None
        # 两个都匹配 "api.service.example.com"
        v.list_sessions.return_value = [s_ex, s_co]
        mock_get_vault.return_value = v

        result = query_session("api.service.example.com")

        assert result["found"] is True
        # 应该匹配更长的 service.example.com
        assert result["domain"] == "service.example.com"
        assert result["matched_by"] == "subdomain"
        assert result["cookies"] == "token=service"

    @patch("core.session.get_vault")
    def test_subdomain_no_false_match(self, mock_get_vault):
        """子域名回退：不匹配不相关的域名（如 myexample.com 不应匹配 example.com）。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "example.com"
        s.cookies = {"__raw__cookie": "token=abc"}
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = None
        v.list_sessions.return_value = [s]
        mock_get_vault.return_value = v

        result = query_session("myexample.com")

        assert result["found"] is False  # myexample.com 不是 example.com 的子域名

    @patch("core.session.get_vault")
    def test_not_found(self, mock_get_vault):
        """完全未命中时返回 found=False。"""
        v = MagicMock()
        v.get_session.return_value = None
        v.list_sessions.return_value = []
        mock_get_vault.return_value = v

        result = query_session("nonexistent.com")

        assert result["found"] is False
        assert result["domain"] == ""
        assert result["matched_by"] == ""
        assert result["cookies"] == ""
        assert result["headers"] == {}
        assert result["auth_tokens"] == []

    @patch("core.session.get_vault")
    def test_expired_filtered_by_default(self, mock_get_vault):
        """默认过滤已过期数据，返回 found=False 但带 expires_at。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "expired.com"
        s.cookies = {"__raw__cookie": "token=old"}
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2025, 1, 1, 12, 0)  # 已过期

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = query_session("expired.com")

        assert result["found"] is False
        assert result["expired"] is True
        assert result["expires_at"] == "2025-01-01T12:00:00"

    @patch("core.session.get_vault")
    def test_include_expired(self, mock_get_vault):
        """include_expired=True 时返回已过期数据。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "expired.com"
        s.cookies = {"__raw__cookie": "token=old"}
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2025, 1, 1, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = query_session("expired.com", include_expired=True)

        assert result["found"] is True
        assert result["expired"] is True
        assert result["cookies"] == "token=old"

    @patch("core.session.get_vault")
    def test_disable_subdomain_match(self, mock_get_vault):
        """subdomain_match=False 时不进行子域名回退。"""
        v = MagicMock()
        v.get_session.return_value = None
        mock_get_vault.return_value = v

        result = query_session("api.example.com", subdomain_match=False)

        assert result["found"] is False
        # 确保没有调用 list_sessions（不做回退扫描）
        v.list_sessions.assert_not_called()

    @patch("core.session.get_vault")
    def test_returns_auth_tokens(self, mock_get_vault):
        """返回认证凭据（localStorage/sessionStorage）。"""
        from datetime import datetime, UTC
        s = MagicMock()
        s.domain = "example.com"
        s.cookies = {
            "__raw__cookie": "token=abc",
            "__auth__ls:access_token": "Bearer xxx",
            "__auth__ss:sess_id": "yyy",
        }
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = query_session("example.com")

        assert result["found"] is True
        assert len(result["auth_tokens"]) == 2
        sources = {t["source"] for t in result["auth_tokens"]}
        assert "localStorage" in sources
        assert "sessionStorage" in sources
