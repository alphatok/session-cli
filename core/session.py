"""
Session CRUD — 站点 Cookie 的存储、查询、删除。

依赖 core.mcp（抓取）和 core.vault（持久化）。

认证凭据编码规则:
    为避免与真实 Cookie 名冲突，auth tokens 以 __auth__ 前缀存入 Vault:
      __auth__ls:{key}  → localStorage 来源
      __auth__ss:{key}  → sessionStorage 来源
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.vault import get_vault, utcnow
from core.mcp import grab_cookies as _grab_cookies_via_mcp  # re-export alias
from core.mcp import AUTH_PREFIX, HDR_PREFIX, RAW_PREFIX, REL_PREFIX, RAW_COOKIE_KEY, URL_KEY


# ── 凭据编码/解码辅助 -------------------------------------------------

def _encode_auth_tokens(cookies: str, auth_tokens: List[dict]) -> Dict[str, str]:
    """将认证凭据以 __auth__ 前缀编码，同时存储原始 cookie 字符串。

    Args:
        cookies: document.cookie 原始字符串
        auth_tokens: 认证凭据列表 [{source, key, value}]

    Returns:
        编码后的 dict（可合并到主 cookies dict）
    """
    merged: Dict[str, str] = {RAW_COOKIE_KEY: cookies}
    for token in auth_tokens:
        source_abbr = "ls" if token["source"] == "localStorage" else "ss"
        key = f"{AUTH_PREFIX}{source_abbr}:{token['key']}"
        merged[key] = token["value"]
    return merged


def _decode_auth_tokens(cookies: Dict[str, str]) -> tuple[str, List[dict]]:
    """从 cookies dict 中分离出原始 cookie 字符串和认证凭据。

    Returns:
        (raw_cookie: str, auth_tokens: list) — 原始 cookie 字符串和认证凭据列表
    """
    raw_cookie = cookies.get(RAW_COOKIE_KEY, "")
    auth_tokens: List[dict] = []

    for key, value in cookies.items():
        if key == RAW_COOKIE_KEY:
            continue
        if key.startswith(AUTH_PREFIX):
            # 解析 "__auth__ls:token_key" 或 "__auth__ss:session_key"
            inner = key[len(AUTH_PREFIX):]  # "ls:token_key" 或 "ss:session_key"
            if ":" in inner:
                source_code, _, token_key = inner.partition(":")
                source = "localStorage" if source_code == "ls" else "sessionStorage"
                auth_tokens.append({
                    "source": source,
                    "key": token_key,
                    "value": value,
                })

    return raw_cookie, auth_tokens


def _encode_headers(
    headers: Dict[str, str],
    raw_requests: List[dict],
) -> Dict[str, str]:
    """将公共 Header 和 raw_requests 编码合并到 cookies 风格的 dict 中。

    编码规则:
        __hdr__{HeaderName} = {HeaderValue}          — 公共 Header
        __raw__requests = JSON字符串                   — 原始请求列表

    Args:
        headers: 公共 Request Header 字典 {key: value}
        raw_requests: 原始请求列表 [{url, method, headers: {key: value}}]

    Returns:
        编码后的 dict（可合并到主 cookies dict）
    """
    encoded: Dict[str, str] = {}
    for key, value in headers.items():
        encoded[f"{HDR_PREFIX}{key}"] = str(value)
    if raw_requests:
        encoded[f"{RAW_PREFIX}requests"] = json.dumps(raw_requests, ensure_ascii=False)
    return encoded


def _decode_headers(
    cookies: Dict[str, str],
) -> tuple[Dict[str, str], List[dict]]:
    """从 cookies dict 中分离出公共 Header 和 raw_requests。

    Returns:
        (headers: {key: value}, raw_requests: [{url, method, headers}])
    """
    headers: Dict[str, str] = {}
    raw_requests: List[dict] = []
    raw_key = f"{RAW_PREFIX}requests"

    for key, value in cookies.items():
        if key == raw_key:
            try:
                raw_requests = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        elif key.startswith(HDR_PREFIX):
            hdr_name = key[len(HDR_PREFIX):]
            headers[hdr_name] = value

    return headers, raw_requests


def _encode_related(related_domains: List[str]) -> Dict[str, str]:
    """将关联域名列表编码为 Vault 键值对。

    编码规则:
        __rel__domains = JSON字符串（去重排序后的域名列表）

    Args:
        related_domains: 域名字符串列表（可能含重复）

    Returns:
        编码后的 dict（可合并到主 cookies dict）
    """
    # 去重并排序
    uniq = sorted(set(d for d in related_domains if d))
    if not uniq:
        return {}
    return {f"{REL_PREFIX}domains": json.dumps(uniq, ensure_ascii=False)}


def _decode_related(cookies: Dict[str, str]) -> List[str]:
    """从 cookies dict 中解码关联域名列表。

    Returns:
        关联域名列表（已去重排序），无数据时返回 []
    """
    key = f"{REL_PREFIX}domains"
    value = cookies.get(key, "")
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _encode_url(original_url: str) -> Dict[str, str]:
    """将原始 URL 编码为 Vault 键值对。

    Args:
        original_url: 用户输入的完整 URL（如 https://chat.deepseek.com/a/chat/s/xxx）

    Returns:
        编码后的 dict（可合并到主 cookies dict）
    """
    if not original_url:
        return {}
    return {URL_KEY: original_url}


def _decode_url(cookies: Dict[str, str]) -> str:
    """从 cookies dict 中解码原始 URL。

    Returns:
        原始 URL 字符串，无数据时返回 ""
    """
    return cookies.get(URL_KEY, "")


# ── 公共 API ──────────────────────────────────────────────────


def grab_cookies(
    domain: str,
    auto_connect: bool = True,
    on_progress: Any = None,
) -> dict:
    """抓取 Cookie + 认证凭据（委托给 mcp 模块）。

    Returns:
        {"cookies": Dict, "auth_tokens": List[dict]}
    """
    return _grab_cookies_via_mcp(domain, auto_connect=auto_connect, on_progress=on_progress)


# ── CRUD ─────────────────────────────────────────────────────

def list_sites() -> List[dict]:
    """列出所有已存储的站点 Session。"""
    vault = get_vault()
    sessions = vault.list_sessions()
    now = utcnow()
    result = []
    for s in sessions:
        raw_cookies = s.cookies if isinstance(s.cookies, dict) else {}
        pure_cookies, auth_tokens = _decode_auth_tokens(raw_cookies)
        headers, raw_requests = _decode_headers(raw_cookies)
        related_domains = _decode_related(raw_cookies)
        original_url = _decode_url(raw_cookies)
        expired = s.expires_at.replace(tzinfo=None) <= now.replace(tzinfo=None)
        result.append({
            "domain": s.domain,
            "original_url": original_url,
            "cookie_count": pure_cookies.count(";") + 1 if pure_cookies else 0,
            "auth_token_count": len(auth_tokens),
            "header_count": len(headers),
            "raw_request_count": len(raw_requests),
            "related_domain_count": len(related_domains),
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "expired": expired,
        })
    return result


def get_site(domain: str) -> Optional[dict]:
    """获取指定站点的 Session 详情（含认证凭据）。"""
    vault = get_vault()
    session = vault.get_session(domain)
    if session is None:
        return None
    raw_cookies = session.cookies if isinstance(session.cookies, dict) else {}
    raw_cookie, auth_tokens = _decode_auth_tokens(raw_cookies)
    headers, raw_requests = _decode_headers(raw_cookies)
    related_domains = _decode_related(raw_cookies)
    original_url = _decode_url(raw_cookies)
    now = utcnow()
    expired = session.expires_at.replace(tzinfo=None) <= now.replace(tzinfo=None)
    return {
        "domain": session.domain,
        "original_url": original_url,
        "cookies": raw_cookie,
        "cookie_count": raw_cookie.count(";") + 1 if raw_cookie else 0,
        "auth_tokens": auth_tokens,
        "auth_token_count": len(auth_tokens),
        "headers": headers,
        "header_count": len(headers),
        "raw_requests": raw_requests,
        "raw_request_count": len(raw_requests),
        "related_domains": related_domains,
        "related_domain_count": len(related_domains),
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "expired": expired,
    }


def store_site(domain: str, data: dict, original_url: str = "") -> dict:
    """存储站点的 Cookie + 认证凭据到 Vault（优先使用真实 Cookie 过期时间，回退 30 天）。

    Args:
        domain: 目标域名（Vault 存储 key）
        data: grab_cookies() 返回的完整 dict，包含 "cookies"（原始字符串）、"auth_tokens" 和可选的 "cookie_expires_at"
        original_url: 用户输入的原始完整 URL（用于后续更新时导航到原始页面）

    Returns:
        {"domain": ..., "original_url": ..., "cookie_count": ..., "auth_token_count": ...}
    """
    cookies = data.get("cookies", "")  # 原始 cookie 字符串
    auth_tokens = data.get("auth_tokens", [])
    headers = data.get("headers", {})
    raw_requests = data.get("raw_requests", [])
    related_domains = data.get("related_domains", [])
    cookie_expires_at = data.get("cookie_expires_at")  # Optional[datetime]

    # 合并 Cookie + Auth Tokens + Headers + Raw Requests + Related Domains + Original URL
    merged = _encode_auth_tokens(cookies, auth_tokens)
    merged.update(_encode_headers(headers, raw_requests))
    merged.update(_encode_related(related_domains))
    merged.update(_encode_url(original_url))

    # 优先使用真实过期时间，回退到 30 天
    real_expiry = cookie_expires_at if isinstance(cookie_expires_at, datetime) else None
    expires_at = real_expiry if real_expiry else utcnow() + timedelta(days=30)

    cookie_count = cookies.count(";") + 1 if cookies else 0
    vault = get_vault()
    vault.store_session(
        domain=domain,
        cookies=merged,
        expires_at=expires_at,
    )
    return {
        "domain": domain,
        "original_url": original_url,
        "cookie_count": cookie_count,
        "auth_token_count": len(auth_tokens),
        "header_count": len(headers),
        "raw_request_count": len(raw_requests),
        "related_domain_count": len(related_domains),
    }


def delete_site(domain: str) -> bool:
    """删除指定站点。"""
    vault = get_vault()
    return vault.delete_session(domain)
