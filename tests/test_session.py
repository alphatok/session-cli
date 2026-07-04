"""core/session.py 测试 — CRUD 操作 + grab_cookies 委托。"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock, patch

import pytest

from core.session import (
    list_sites, get_site, store_site, delete_site,
    _encode_auth_tokens, _decode_auth_tokens,
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
        s.cookies = {"token": "abc", "uid": "123"}
        s.created_at = datetime(2026, 1, 1, 12, 0)
        s.expires_at = datetime(2026, 12, 31, 12, 0)

        v = MagicMock()
        v.get_session.return_value = s
        mock_get_vault.return_value = v

        result = get_site("example.com")
        assert result["domain"] == "example.com"
        assert result["cookie_count"] == 2
        assert result["cookies"]["token"] == "abc"
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

        data = {"cookies": {"key": "val"}, "auth_tokens": []}
        result = store_site("test.com", data)
        assert result["domain"] == "test.com"
        assert result["cookie_count"] == 1

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
        assert stored_cookies["token"] == "abc123"


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
        cookies = {"a": "1", "b": "2"}
        auth = [
            {"source": "localStorage", "key": "access_token", "value": "xxx"},
            {"source": "sessionStorage", "key": "sess_id", "value": "yyy"},
        ]
        result = _encode_auth_tokens(cookies, auth)

        assert result["a"] == "1"  # 原始 cookie 保留
        assert result["b"] == "2"
        assert result["__auth__ls:access_token"] == "xxx"
        assert result["__auth__ss:sess_id"] == "yyy"
        assert len(result) == 4

    def test_encode_does_not_mutate_original(self):
        """编码不修改原始 dict。"""
        cookies = {"c": "3"}
        auth = [{"source": "localStorage", "key": "t", "value": "v"}]
        _encode_auth_tokens(cookies, auth)
        assert "__auth__" not in str(cookies)  # 原始 dict 未被修改

    def test_decode_separates_auth_from_cookies(self, sample_auth_encoded_cookies):
        """解码将 __auth__ 条目分离为 auth_tokens。"""
        pure, auth = _decode_auth_tokens(sample_auth_encoded_cookies)

        assert len(pure) == 2
        assert pure["token"] == "abc123"
        assert pure["session"] == "xyz789"

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
        pure, auth = _decode_auth_tokens({"a": "1", "b": "2"})
        assert pure == {"a": "1", "b": "2"}
        assert auth == []

    def test_decode_all_auth_no_cookies(self):
        """全部是 __auth__ 条目时 pure cookies 为空。"""
        pure, auth = _decode_auth_tokens({
            "__auth__ls:t1": "v1",
            "__auth__ss:t2": "v2",
        })
        assert pure == {}
        assert len(auth) == 2

    def test_roundtrip_encode_decode(self, sample_grab_enriched):
        """编码 → 解码 往返保持凭据完整性。"""
        encoded = _encode_auth_tokens(
            sample_grab_enriched["cookies"],
            sample_grab_enriched["auth_tokens"],
        )
        pure, auth = _decode_auth_tokens(encoded)

        assert pure == sample_grab_enriched["cookies"]
        assert len(auth) == len(sample_grab_enriched["auth_tokens"])
