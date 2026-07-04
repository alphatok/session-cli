"""
Session CLI Core — 统一公共 API

模块:
    mcp      — MCP JSON-RPC 通信层（chrome-devtools-mcp）
    vault    — Romek Vault 管理器（单例 + 线程安全）
    session  — Cookie 抓取 + CRUD 业务逻辑
"""

from core.mcp import grab_cookies
from core.vault import get_vault, init_vault, unlock_vault
from core.session import list_sites, get_site, store_site, delete_site, query_session

__all__ = [
    # MCP
    "grab_cookies",
    # Vault
    "get_vault",
    "init_vault",
    "unlock_vault",
    # Session CRUD
    "list_sites",
    "get_site",
    "store_site",
    "delete_site",
    # Lookup
    "query_session",
]
