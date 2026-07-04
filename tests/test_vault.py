"""core/vault.py 测试 — VaultManager 单例管理、生命周期、线程安全。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core import vault
from romek.vault import VaultAuthenticationError, VaultNotInitializedError


class TestGetVault:
    """Vault 单例获取（Bug #1, #2 修复验证）。"""

    def setup_method(self):
        vault.reset_vault()

    def teardown_method(self):
        vault.reset_vault()

    @patch("core.vault.Vault")
    def test_returns_same_instance(self, MockVault):
        """多次调用返回同一个单例。"""
        MockVault.return_value.is_initialized.return_value = True
        MockVault.return_value.password = "pw"

        v1 = vault.get_vault()
        v2 = vault.get_vault()
        assert v1 is v2

    @patch("core.vault.Vault")
    def test_does_not_raise_on_uninitialized(self, MockVault):
        """未初始化时不抛异常，返回 Vault 实例（Bug #2 修复）。"""
        v = MagicMock()
        v.is_initialized.return_value = False
        v.password = None
        MockVault.return_value = v

        result = vault.get_vault(auto_unlock=False)
        assert result is v
        v.unlock.assert_not_called()

    @patch("core.vault.Vault")
    def test_auto_unlock_calls_unlock(self, MockVault):
        """auto_unlock=True 时调用 unlock()。"""
        v = MagicMock()
        v.is_initialized.return_value = True
        v.password = None
        MockVault.return_value = v

        vault.get_vault(auto_unlock=True)
        v.unlock.assert_called_once()

    @patch("core.vault.Vault")
    def test_auto_unlock_skips_if_already_unlocked(self, MockVault):
        """已解锁时不重复调用 unlock()。"""
        v = MagicMock()
        v.is_initialized.return_value = True
        v.password = "already-set"
        MockVault.return_value = v

        vault.get_vault(auto_unlock=True)
        v.unlock.assert_not_called()


class TestInitVault:
    """Vault 初始化测试。"""

    def setup_method(self):
        vault.reset_vault()

    def teardown_method(self):
        vault.reset_vault()

    @patch("core.vault.Vault")
    def test_successful_init(self, MockVault):
        """成功初始化 Vault。"""
        v = MagicMock()
        v.is_initialized.return_value = False
        MockVault.return_value = v

        result = vault.init_vault("mypassword")
        assert result is True
        v.initialize.assert_called_once_with("mypassword")

    @patch("core.vault.Vault")
    def test_already_initialized(self, MockVault):
        """已初始化时返回 False。"""
        v = MagicMock()
        v.is_initialized.return_value = True
        MockVault.return_value = v

        result = vault.init_vault("mypassword")
        assert result is False
        v.initialize.assert_not_called()

    @patch("core.vault.Vault")
    def test_init_sets_global(self, MockVault):
        """初始化后 _vault 单例被设置。"""
        v = MagicMock()
        v.is_initialized.return_value = False
        MockVault.return_value = v

        vault.init_vault("pw")
        assert vault._vault is v


class TestUnlockVault:
    """Vault 解锁测试。"""

    def setup_method(self):
        vault.reset_vault()

    def teardown_method(self):
        vault.reset_vault()

    @patch("core.vault.Vault")
    def test_successful_unlock(self, MockVault):
        """成功解锁。"""
        v = MagicMock()
        v.is_initialized.return_value = True
        MockVault.return_value = v

        result = vault.unlock_vault("correct")
        assert result is True
        v.unlock.assert_called_once_with("correct")

    @patch("core.vault.Vault")
    def test_unlock_not_initialized(self, MockVault):
        """未初始化时返回 False。"""
        v = MagicMock()
        v.is_initialized.return_value = False
        MockVault.return_value = v

        result = vault.unlock_vault("pw")
        assert result is False

    @patch("core.vault.Vault")
    def test_unlock_wrong_password(self, MockVault):
        """错误密码返回 False。"""
        v = MagicMock()
        v.is_initialized.return_value = True
        v.unlock.side_effect = VaultAuthenticationError("wrong")
        MockVault.return_value = v

        result = vault.unlock_vault("wrong")
        assert result is False


class TestIsVaultReady:
    """is_vault_ready 状态检查。"""

    def setup_method(self):
        vault.reset_vault()

    def teardown_method(self):
        vault.reset_vault()

    @patch("core.vault.Vault")
    def test_ready(self, MockVault):
        v = MagicMock()
        v.is_initialized.return_value = True
        v.password = "pw"
        MockVault.return_value = v

        assert vault.is_vault_ready() is True

    @patch("core.vault.Vault")
    def test_not_initialized(self, MockVault):
        v = MagicMock()
        v.is_initialized.return_value = False
        v.password = None
        MockVault.return_value = v

        assert vault.is_vault_ready() is False


class TestUtcnow:
    """utcnow 替代 datetime.utcnow()（Bug #6 修复验证）。"""

    def test_returns_utc_datetime(self):
        """返回的是 UTC 时区 datetime。"""
        from datetime import UTC
        result = vault.utcnow()
        assert result.tzinfo == UTC


class TestResetVault:
    """reset_vault（测试辅助）。"""

    @patch("core.vault.Vault")
    def test_clears_global(self, MockVault):
        MockVault.return_value.is_initialized.return_value = True
        MockVault.return_value.password = "pw"

        v1 = vault.get_vault()
        assert vault._vault is not None

        vault.reset_vault()
        assert vault._vault is None
