"""
Session CRUD — 站点 Cookie 的存储、查询、删除。

依赖 core.mcp（抓取）和 core.vault（持久化）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from core.vault import get_vault, utcnow
from core.mcp import grab_cookies as _grab_cookies_via_mcp  # re-export alias


def grab_cookies(
    domain: str,
    auto_connect: bool = True,
    on_progress=None,
) -> Dict[str, str]:
    """抓取 Cookie（委托给 mcp 模块）。"""
    return _grab_cookies_via_mcp(domain, auto_connect=auto_connect, on_progress=on_progress)


# ── CRUD ─────────────────────────────────────────────────────

def list_sites() -> List[dict]:
    """列出所有已存储的站点 Session。"""
    vault = get_vault()
    sessions = vault.list_sessions()
    now = utcnow()
    result = []
    for s in sessions:
        expired = s.expires_at.replace(tzinfo=None) <= now.replace(tzinfo=None)
        result.append({
            "domain": s.domain,
            "cookie_count": len(s.cookies),
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "expired": expired,
        })
    return result


def get_site(domain: str) -> Optional[dict]:
    """获取指定站点的 Session 详情。"""
    vault = get_vault()
    session = vault.get_session(domain)
    if session is None:
        return None
    now = utcnow()
    expired = session.expires_at.replace(tzinfo=None) <= now.replace(tzinfo=None)
    return {
        "domain": session.domain,
        "cookies": session.cookies,
        "cookie_count": len(session.cookies),
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "expired": expired,
    }


def store_site(domain: str, cookies: Dict[str, str]) -> dict:
    """存储站点的 Cookie 到 Vault（默认 30 天过期）。"""
    vault = get_vault()
    session = vault.store_session(
        domain=domain,
        cookies=cookies,
        expires_at=utcnow() + timedelta(days=30),
    )
    return {"domain": session.domain, "cookie_count": len(cookies)}


def delete_site(domain: str) -> bool:
    """删除指定站点。"""
    vault = get_vault()
    return vault.delete_session(domain)
