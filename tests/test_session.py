"""core/session.py 测试 — CRUD 操作 + grab_cookies 委托。"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock, patch

import pytest

from core.session import list_sites, get_site, store_site, delete_site


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
        assert result[0]["cookie_count"] == 2
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
        """默认 30 天过期。"""
        from datetime import datetime, UTC
        v = MagicMock()

        def capture_store(**kwargs):
            s = MagicMock()
            s.domain = kwargs["domain"]
            return s

        v.store_session.side_effect = capture_store
        mock_get_vault.return_value = v

        result = store_site("test.com", {"key": "val"})
        assert result["domain"] == "test.com"
        assert result["cookie_count"] == 1

        # 验证传入的 expires_at 约在 30 天后
        call_kwargs = v.store_session.call_args[1]
        assert "expires_at" in call_kwargs
        v.close.assert_not_called()


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
