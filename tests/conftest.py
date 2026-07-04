"""共享 fixtures 和 mock 对象。"""

from __future__ import annotations

import json
import queue
import sys
import threading
from unittest.mock import MagicMock, patch
from io import StringIO

from pathlib import Path

import pytest

# Make core importable in CI
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_vault():
    """返回一个配置了基本行为的 mock Vault 对象。"""
    v = MagicMock()
    v.is_initialized.return_value = True
    v.password = "test-pass"
    v.salt = b"test-salt-16byte"
    return v


@pytest.fixture
def mock_vault_uninitialized():
    """返回一个未初始化的 mock Vault。"""
    v = MagicMock()
    v.is_initialized.return_value = False
    v.password = None
    v.salt = None
    return v


@pytest.fixture
def mock_subprocess():
    """返回一个 mock subprocess.Popen 对象。"""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.poll.return_value = None
    return proc


@pytest.fixture
def sample_session_rows():
    """模拟 romek models.Session 列表。"""
    from datetime import datetime, timedelta, UTC

    s1 = MagicMock()
    s1.domain = "example.com"
    s1.cookies = {"token": "abc123", "session": "xyz789", "__auth__ls:auth_token": "Bearer eyJ..."}
    s1.created_at = datetime(2026, 1, 1, 12, 0)
    s1.expires_at = datetime(2026, 12, 31, 12, 0)
    s1.id = "uuid-1"

    s2 = MagicMock()
    s2.domain = "test.org"
    s2.cookies = {"auth": "def456"}
    s2.created_at = datetime(2026, 6, 1, 12, 0)
    s2.expires_at = datetime(2026, 6, 2, 12, 0)  # expired
    s2.id = "uuid-2"

    return [s1, s2]


@pytest.fixture
def capture_stdout():
    """捕获 stdout 输出。"""
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    yield buf
    sys.stdout = old


@pytest.fixture
def progress_queue():
    """一个空的进度队列。"""
    return queue.Queue()


@pytest.fixture
def sample_mcp_page_list():
    """模拟 list_pages 的 Markdown 返回。"""
    return (
        "## Pages\n"
        "1: https://github.com/user/repo [selected]\n"
        "2: Figma Design (https://www.figma.com/file/abc)\n"
        "3: Chat (https://yuanbao.tencent.com/chat/naQivTmsDa)\n"
    )


@pytest.fixture
def sample_mcp_cookie_result():
    """模拟旧版 evaluate_script 的 Markdown 返回（name=value 字符串）。"""
    return (
        "Script ran on page and returned:\n"
        '```json\n'
        '"token=abc123; session=xyz789; uid=user001"\n'
        '```'
    )


@pytest.fixture
def sample_mcp_grab_json():
    """模拟新版 evaluate_script 的增强 JS 返回（JSON 对象）。"""
    return (
        "Script ran on page and returned:\n"
        "```json\n"
        '{"cookies":[{"name":"token","value":"abc123"},{"name":"session","value":"xyz789"}],'
        '"storage":{"localStorage":{"auth_token":"Bearer eyJhbGciOiJIUzI1NiJ9.xxx","refresh_token":"rt_abc123"},'
        '"sessionStorage":{}}}'
        "\n```"
    )


@pytest.fixture
def sample_grab_enriched():
    """模拟 grab_cookies 的增强返回结构。"""
    return {
        "cookies": {"token": "abc123", "session": "xyz789"},
        "auth_tokens": [
            {"source": "localStorage", "key": "auth_token", "value": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx"},
            {"source": "localStorage", "key": "refresh_token", "value": "rt_abc123"},
        ],
    }


@pytest.fixture
def sample_auth_encoded_cookies():
    """模拟编码后的 cookies dict（含 __auth__ 前缀凭据）。"""
    return {
        "token": "abc123",
        "session": "xyz789",
        "__auth__ls:auth_token": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx",
        "__auth__ls:refresh_token": "rt_abc123",
        "__auth__ss:session_id": "sess_456",
    }


# ── Network Headers 测试 fixtures ──────────────────────────

@pytest.fixture
def sample_network_list_md():
    """模拟 list_network_requests 返回的 Markdown 表格。"""
    return (
        "## Network Requests\n"
        "Showing 1-8 of 20\n"
        "| ReqId | Method | URL | Status | Type |\n"
        "|-------|--------|-----|--------|------|\n"
        "| 1 | GET | https://example.com/ | 200 | Document |\n"
        "| 2 | GET | https://example.com/style.css | 200 | Stylesheet |\n"
        "| 3 | GET | https://example.com/api/me | 200 | XHR |\n"
        "| 4 | POST | https://example.com/api/data | 201 | XHR |\n"
        "| 5 | GET | https://other.com/analytics | 200 | XHR |\n"
        "| 6 | GET | https://example.com/api/config | 200 | Fetch |\n"
        "| 7 | GET | https://cdn.example.com/lib.js | 200 | Script |\n"
        "| 8 | GET | https://example.com/favicon.ico | 200 | Image |\n"
    )


@pytest.fixture
def sample_network_detail_md():
    """模拟 get_network_request 返回的详细视图。"""
    return (
        "## Request #3\n"
        "URL: https://example.com/api/me\n"
        "Method: GET\n"
        "Status: 200\n\n"
        "### Request Headers\n"
        "- Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx\n"
        "- User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\n"
        "- Accept: application/json, text/plain, */*\n"
        "- Accept-Language: zh-CN,zh;q=0.9,en;q=0.8\n"
        "- Referer: https://example.com/\n\n"
        "### Response Headers\n"
        "- Content-Type: application/json\n"
        "- Cache-Control: no-cache\n"
    )


@pytest.fixture
def sample_network_detail_md2():
    """模拟第二个请求的详情（不同 referer，auth 一致）。"""
    return (
        "## Request #4\n"
        "URL: https://example.com/api/data\n"
        "Method: POST\n"
        "Status: 201\n\n"
        "### Request Headers\n"
        "- Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx\n"
        "- User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\n"
        "- Accept: application/json\n"
        "- Content-Type: application/json\n"
        "- Referer: https://example.com/dashboard\n"
        "- Cookie: session=abc\n\n"
        "### Response Headers\n"
        "- Content-Type: application/json\n"
    )


@pytest.fixture
def sample_grab_with_headers():
    """模拟完整的抓取返回结构（含 headers + raw_requests）。"""
    return {
        "cookies": {"token": "abc123", "session": "xyz789"},
        "auth_tokens": [
            {"source": "localStorage", "key": "auth_token", "value": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx"},
        ],
        "headers": {
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        },
        "raw_requests": [
            {
                "url": "https://example.com/api/me",
                "method": "GET",
                "headers": {
                    "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://example.com/",
                },
            },
            {
                "url": "https://example.com/api/data",
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.xxx",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Referer": "https://example.com/dashboard",
                },
            },
        ],
    }


@pytest.fixture
def sample_header_encoded_cookies():
    """模拟编码后的 cookies dict（含 __hdr__ 和 __raw__ 前缀）。"""
    import json
    raw = [
        {"url": "https://example.com/api/me", "method": "GET",
         "headers": {"Authorization": "Bearer xxx", "User-Agent": "Mozilla/5.0"}},
    ]
    return {
        "token": "abc123",
        "__hdr__Authorization": "Bearer xxx",
        "__hdr__User-Agent": "Mozilla/5.0",
        "__raw__requests": json.dumps(raw),
    }
