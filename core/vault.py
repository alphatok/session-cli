"""
Romek Vault 管理器 — 单例 Vault 生命周期管理。

特点:
    - 延迟初始化：不影响未初始化 vault 时的导入
    - 线程安全：使用锁保护单例状态
    - 不主动 close：Vault._connection 会自动重连，无需手动管理
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, UTC
from typing import Optional

from romek import Vault
from romek.vault import VaultAuthenticationError, VaultNotInitializedError, VaultError

# ── 全局状态 ──────────────────────────────────────────────────

_vault: Optional[Vault] = None
_vault_lock = threading.Lock()


def reset_vault() -> None:
    """**仅测试用** — 重置全局 Vault 单例状态。"""
    global _vault
    with _vault_lock:
        _vault = None


def get_vault(auto_unlock: bool = True) -> Vault:
    """获取全局 Vault 单例。

    首次调用时创建 Vault 实例。如果 vault 尚未初始化，不会抛异常，
    而是返回未解锁的 Vault 对象供调用方自行处理。

    Args:
        auto_unlock: 是否自动通过系统 keyring 解锁（默认 True）

    Returns:
        全局 Vault 实例

    Raises:
        VaultAuthenticationError: auto_unlock=True 且 keyring 解锁失败
        VaultNotInitializedError: auto_unlock=True 且 vault 未初始化
    """
    global _vault
    with _vault_lock:
        if _vault is None:
            _vault = Vault()
        vault = _vault

    if auto_unlock and vault.is_initialized() and vault.password is None:
        vault.unlock()  # 从系统 keyring 自动获取密码

    return vault


def unlock_vault(password: str) -> bool:
    """用密码解锁 Vault。

    Args:
        password: 主密码

    Returns:
        True 表示解锁成功
    """
    global _vault
    try:
        vault = Vault()
        if not vault.is_initialized():
            return False
        vault.unlock(password)
        with _vault_lock:
            _vault = vault
        return True
    except VaultAuthenticationError:
        return False


def init_vault(password: str) -> bool:
    """初始化 Vault（首次使用）。

    Args:
        password: 主密码

    Returns:
        True 表示初始化成功
    """
    global _vault
    try:
        vault = Vault()
        if vault.is_initialized():
            return False
        vault.initialize(password)
        with _vault_lock:
            _vault = vault
        return True
    except VaultError:
        return False


def is_vault_ready() -> bool:
    """检查 Vault 是否已初始化并解锁。"""
    vault = get_vault(auto_unlock=False)
    return vault.is_initialized() and vault.password is not None


def utcnow() -> datetime:
    """当前 UTC 时间（替代已废弃的 datetime.utcnow()）。"""
    return datetime.now(UTC)

# Re-export exceptions for convenience
__all__ = [
    "get_vault", "init_vault", "unlock_vault",
    "reset_vault", "is_vault_ready", "utcnow",
    "VaultAuthenticationError", "VaultNotInitializedError", "VaultError",
]
