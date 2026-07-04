"""core/mcp.py 测试 — MCP JSON-RPC 通信、Cookie 提取、Markdown 解析。"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest

from core.mcp import (
    _extract_markdown_json,
    _extract_markdown_json_obj,
    _extract_result,
    _find_npx,
    _jsonrpc_send,
    _parse_network_list_table,
    _parse_network_request_detail,
    _parse_cookie_expiry,
    _compute_common_headers,
    _extract_hostname,
    _is_same_or_subdomain,
    HDR_PREFIX,
    RAW_PREFIX,
)


class TestFindNpx:
    """跨平台 npx 查找（Bug #12 修复验证）。"""

    @patch("core.mcp.os.name", "nt")
    @patch("core.mcp.os.path.isfile")
    @patch("core.mcp.os.environ.get")
    def test_find_on_windows(self, mock_env, mock_isfile):
        """Windows 上能找到 npx.cmd。"""
        mock_env.return_value = r"C:\Program Files"
        mock_isfile.side_effect = lambda p: "Program Files" in p

        result = _find_npx()
        assert result is not None
        assert "npx.cmd" in result

    @patch("core.mcp.os.name", "posix")
    @patch("core.mcp.os.path.isfile")
    def test_find_on_linux(self, mock_isfile):
        """Linux 上能找到 npx。"""
        mock_isfile.side_effect = lambda p: "/usr/local/bin/npx" in p

        result = _find_npx()
        assert result == "/usr/local/bin/npx"

    @patch("core.mcp.os.name", "nt")
    @patch("core.mcp.os.path.isfile", return_value=False)
    @patch("core.mcp.shutil.which", return_value="C:\\nodejs\\npx.cmd")
    def test_fallback_to_path(self, mock_which, mock_isfile):
        """找不到文件时回退到 PATH 查找。"""
        result = _find_npx()
        assert result == "C:\\nodejs\\npx.cmd"


class TestJsonrpcSend:
    """JSON-RPC 通信测试（Bug #3 修复验证）。"""

    def test_sends_correct_format(self, mock_subprocess):
        """正确格式的 JSON-RPC 请求。"""
        mock_subprocess.stdout.readline.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1234567890000,
            "result": {"ok": True},
        }) + "\n"

        with patch("core.mcp.time.time", return_value=1234567890):
            result = _jsonrpc_send(mock_subprocess, "test/method", {"key": "val"})

        assert result["result"]["ok"] is True
        mock_subprocess.stdin.write.assert_called_once()

    def test_handles_non_matching_responses(self, mock_subprocess):
        """跳过不匹配 id 的消息，继续等待正确响应。"""
        lines = iter([
            json.dumps({"jsonrpc": "2.0", "method": "notification", "params": {}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 999, "result": "wrong"}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 1234567890000, "result": "correct"}) + "\n",
        ])
        mock_subprocess.stdout.readline = lambda: next(lines)

        with patch("core.mcp.time.time", return_value=1234567890):
            result = _jsonrpc_send(mock_subprocess, "test/method", {})

        assert result["result"] == "correct"

    def test_handles_json_decode_errors(self, mock_subprocess):
        """忽略 JSON 解析错误的行。"""
        lines = iter([
            "garbage line\n",
            json.dumps({"jsonrpc": "2.0", "id": 1234567890000, "result": "ok"}) + "\n",
        ])
        mock_subprocess.stdout.readline = lambda: next(lines)

        with patch("core.mcp.time.time", return_value=1234567890):
            result = _jsonrpc_send(mock_subprocess, "test/method", {})

        assert result["result"] == "ok"

    def test_timeout_returns_error(self, mock_subprocess):
        """超时返回错误而不是死循环。"""
        mock_subprocess.stdout.readline.return_value = ""

        # readline 始终返回空行导致循环继续，需要足够多的 time 值触发超时
        with patch("core.mcp.time.time", side_effect=[1000, 1001, 1002, 2000]):
            result = _jsonrpc_send(mock_subprocess, "test/method", {})

        assert "error" in result
        assert "Timeout" in result["error"]


class TestExtractResult:
    """MCP tools/call 响应内容提取。"""

    def test_extracts_text_content(self):
        resp = {
            "result": {
                "content": [
                    {"type": "text", "text": "hello world"},
                ],
            },
        }
        assert _extract_result(resp) == "hello world"

    def test_returns_str_for_non_dict(self):
        assert _extract_result({"result": 42}) == "42"

    def test_raises_on_error(self):
        with pytest.raises(RuntimeError, match="MCP error"):
            _extract_result({"error": {"code": -1, "message": "fail"}})


class TestExtractMarkdownJson:
    """Markdown JSON 提取（Bug #8 修复验证）。"""

    def test_standard_format(self):
        """标准格式：```json ... ```。"""
        text = 'Script ran on page and returned:\n```json\n"cookie1=val1; cookie2=val2"\n```'
        result = _extract_markdown_json(text)
        assert result == "cookie1=val1; cookie2=val2"

    def test_without_language_tag(self):
        """code block 无 json 标记。"""
        text = 'Script ran...\n```\n"a=1; b=2"\n```'
        result = _extract_markdown_json(text)
        assert result == "a=1; b=2"

    def test_complex_cookie_value(self):
        """Cookie 值包含特殊字符。"""
        text = '```json\n"token=eyJhbGciOiJIUzI1NiJ9.abc; uid=123"\n```'
        result = _extract_markdown_json(text)
        assert "token=eyJhbGciOiJIUzI1NiJ9" in result
        assert "uid=123" in result

    def test_empty_text_returns_empty(self):
        """空字符串返回空。"""
        assert _extract_markdown_json("") == ""

    def test_no_code_block_returns_original(self):
        """无代码块的文本返回原始内容（fallback 策略）。"""
        assert _extract_markdown_json("no code block") == "no code block"

    def test_non_string_returns_empty(self):
        assert _extract_markdown_json(None) == ""
        assert _extract_markdown_json(42) == ""


class TestExtractMarkdownJsonObj:
    """增强版 Markdown JSON 对象提取（v2 新增）。"""

    def test_extracts_json_object(self, sample_mcp_grab_json):
        """从 Markdown 中提取 JSON 对象。"""
        result = _extract_markdown_json_obj(sample_mcp_grab_json)
        assert result is not None
        assert "cookie" in result
        assert result["cookie"] == "token=abc123; session=xyz789"
        assert result["localStorage"]["auth_token"] == "Bearer eyJhbGciOiJIUzI1NiJ9.xxx"

    def test_parses_auth_tokens(self, sample_mcp_grab_json):
        """auth_token 从 localStorage 正确提取。"""
        result = _extract_markdown_json_obj(sample_mcp_grab_json)
        assert "refresh_token" in result["localStorage"]
        assert result["localStorage"]["refresh_token"] == "rt_abc123"

    def test_json_without_language_tag(self):
        """无 json 语言标记的 code block 也可解析。"""
        text = '```\n{"cookie":"a=1","localStorage":{},"sessionStorage":{}}\n```'
        result = _extract_markdown_json_obj(text)
        assert result is not None
        assert result["cookie"] == "a=1"

    def test_empty_storage(self):
        """空 localStorage/sessionStorage 返回空 dict。"""
        text = '```json\n{"cookie":"","localStorage":{},"sessionStorage":{}}\n```'
        result = _extract_markdown_json_obj(text)
        assert result is not None
        assert result["localStorage"] == {}

    def test_falls_back_to_regex_pattern(self):
        """非标准格式的回退解析（策略 3/4）。"""
        text = 'Some prefix text {"cookie":"token=abc; uid=123","localStorage":{},"sessionStorage":{}} some suffix'
        result = _extract_markdown_json_obj(text)
        assert result is not None
        assert result["cookie"] == "token=abc; uid=123"

    def test_non_string_returns_none(self):
        assert _extract_markdown_json_obj(None) is None
        assert _extract_markdown_json_obj(42) is None

    def test_invalid_json_returns_none(self):
        assert _extract_markdown_json_obj("not json at all") is None
        assert _extract_markdown_json_obj("```json\n{invalid}\n```") is None


class TestGrabCookiesIntegration:
    """grab_cookies 流程测试（mock _jsonrpc_send 直接返回预设响应）。"""

    @patch("core.mcp._start_mcp_server")
    @patch("core.mcp.time.sleep", return_value=None)
    def test_full_grab_flow(self, mock_sleep, mock_start, mock_subprocess):
        """完整抓取流程：list → select/navigate → network → evaluate → parse。"""
        mock_start.return_value = mock_subprocess

        # 直接 mock _jsonrpc_send 返回预设响应，避免 ID 匹配复杂性
        list_text = (
            "## Pages\n"
            "1: https://other.site.com [selected]\n"
            "2: https://test.example.com/dashboard\n"
        )
        # 网络请求列表（空，跳过 header 捕获）
        network_list_text = "## Network Requests\nNo requests recorded."
        cookie_text = (
            'Script ran on page and returned:\n'
            '```json\n'
            '{"cookie":"token=abc; uid=123",'
            '"localStorage":{"auth_key":"secret123"},"sessionStorage":{}}'
            '\n```'
        )

        # _jsonrpc_send 按调用顺序返回 list → select → navigate → list_network_requests → evaluate
        send_responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": list_text}]}},
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Switched"}]}},
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Navigated to https://test.example.com"}]}},
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": network_list_text}]}},
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": cookie_text}]}},
        ]
        send_iter = iter(send_responses)

        from core.mcp import grab_cookies

        progress_stages = []

        with patch("core.mcp._jsonrpc_send", side_effect=lambda *a, **kw: next(send_iter)):
            result = grab_cookies(
                "test.example.com",
                auto_connect=False,
                on_progress=lambda s, d: progress_stages.append(s),
            )

        assert isinstance(result, dict)
        assert "cookies" in result
        assert "auth_tokens" in result
        assert "headers" in result
        assert "raw_requests" in result
        assert "related_domains" in result
        assert result["cookies"] == "token=abc; uid=123"
        assert len(result["auth_tokens"]) == 1
        assert result["auth_tokens"][0]["key"] == "auth_key"
        assert result["auth_tokens"][0]["source"] == "localStorage"
        # 空网络请求应返回空 headers/raw_requests/related_domains
        assert result["headers"] == {}
        assert result["raw_requests"] == []
        assert result["related_domains"] == []
        for s in ("listing",):
            assert s in progress_stages, f"Missing stage: {s}"


# ── Network Header 解析器测试 ────────────────────────────────


class TestParseNetworkListTable:
    """list_network_requests Markdown 表格解析。"""

    def test_parses_matching_domain(self, sample_network_list_md):
        """提取目标域名匹配的 reqid，同时收集全部 hostname。"""
        reqids, all_hostnames = _parse_network_list_table(sample_network_list_md, "example.com")
        assert 1 in reqids
        assert 3 in reqids
        assert 5 not in reqids  # other.com
        # all_hostnames 包含表格中所有独特 hostname
        assert "example.com" in all_hostnames
        assert "other.com" in all_hostnames

    def test_case_insensitive(self):
        """域名匹配不区分大小写。"""
        text = "| ReqId | Method | URL |\n|---|---|---|\n| 1 | GET | https://EXAMPLE.COM/api | 200 |"
        reqids, _ = _parse_network_list_table(text, "example.com")
        assert reqids == [1]

    def test_empty_returns_empty(self):
        assert _parse_network_list_table("", "example.com") == ([], set())
        assert _parse_network_list_table(None, "example.com") == ([], set())

    def test_no_match_returns_empty(self):
        text = "| 1 | GET | https://other.com | 200 |"
        reqids, _ = _parse_network_list_table(text, "example.com")
        assert reqids == []

    def test_subdomain_matches(self):
        """子域名应被正确匹配。"""
        text = (
            "| ReqId | Method | URL | Status |\n"
            "|---|---|---|---|\n"
            "| 1 | GET | https://api.example.com/data | 200 |\n"
            "| 2 | GET | https://cdn.static.example.com/lib.js | 200 |\n"
            "| 3 | GET | https://notexample.com | 200 |\n"
        )
        reqids, all_hostnames = _parse_network_list_table(text, "example.com")
        assert 1 in reqids
        assert 2 in reqids
        assert 3 not in reqids  # notexample.com 不应匹配
        assert "api.example.com" in all_hostnames
        assert "cdn.static.example.com" in all_hostnames
        assert "notexample.com" in all_hostnames

    def test_new_format_reqid_style(self, sample_network_list_new_md):
        """新版 reqid=1 GET URL [200] 格式解析。"""
        reqids, all_hostnames = _parse_network_list_table(sample_network_list_new_md, "example.com")
        assert 1 in reqids
        assert 2 in reqids
        assert 3 not in reqids  # other.com
        assert "example.com" in all_hostnames
        assert "other.com" in all_hostnames

    def test_new_format_mixed_with_old(self):
        """新版格式优先匹配，不会误触发旧版表格解析。"""
        text = (
            "## Network requests\n"
            "reqid=1 GET https://example.com/api [200]\n"
        )
        reqids, _ = _parse_network_list_table(text, "example.com")
        assert reqids == [1]


class TestParseNetworkRequestDetail:
    """get_network_request 详细视图解析。"""

    def test_parses_request_headers(self, sample_network_detail_md):
        """提取 URL、Method、Request Headers。"""
        result = _parse_network_request_detail(sample_network_detail_md)
        assert result is not None
        assert result["url"] == "https://example.com/api/me"
        assert result["method"] == "GET"
        assert "Authorization" in result["headers"]
        assert result["headers"]["Authorization"] == "Bearer eyJhbGciOiJIUzI1NiJ9.xxx"
        assert "User-Agent" in result["headers"]
        assert "Content-Type" not in result["headers"]  # 不包含 Response Headers

    def test_empty_returns_none(self):
        assert _parse_network_request_detail("") is None
        assert _parse_network_request_detail(None) is None

    def test_no_request_headers_section(self):
        """无 Request Headers 区块时返回空 headers。"""
        text = "## Request #1\nURL: https://example.com/\nMethod: GET\nStatus: 200"
        result = _parse_network_request_detail(text)
        assert result is not None
        assert result["url"] == "https://example.com/"
        assert result["headers"] == {}

    def test_new_format_url_in_title(self, sample_network_detail_new_md):
        """新版格式：URL 在 ## Request 标题中，compact headers。"""
        result = _parse_network_request_detail(sample_network_detail_new_md)
        assert result is not None
        assert result["url"] == "https://example.com/api/me"
        # 新版格式没有独立 Method 行，默认为 GET
        assert result["method"] == "GET"
        assert "authorization" in result["headers"]
        assert result["headers"]["authorization"] == "Bearer eyJhbGciOiJIUzI1NiJ9.xxx"
        assert "user-agent" in result["headers"]
        # H2 伪头部正常解析
        assert ":authority" in result["headers"]
        assert result["headers"][":authority"] == "example.com"
        # 不包含 Response Headers
        assert "content-type" not in result["headers"]

    def test_old_format_still_works(self, sample_network_detail_md):
        """旧版格式仍然正常工作。"""
        result = _parse_network_request_detail(sample_network_detail_md)
        assert result is not None
        assert result["url"] == "https://example.com/api/me"
        assert result["method"] == "GET"
        assert "Authorization" in result["headers"]


    def test_parses_set_cookie_from_response(self, sample_network_detail_with_setcookie):
        """从 Response Headers 中提取 Set-Cookie 值。"""
        result = _parse_network_request_detail(sample_network_detail_with_setcookie)
        assert result is not None
        assert result["url"] == "https://example.com/api/login"
        assert "authorization" in result["headers"]
        assert len(result["set_cookies"]) == 2
        assert "session=abc123" in result["set_cookies"][0]
        assert "Max-Age=3600" in result["set_cookies"][1]

    def test_new_format_no_set_cookie(self, sample_network_detail_new_md):
        """无 Set-Cookie 时返回空列表。"""
        result = _parse_network_request_detail(sample_network_detail_new_md)
        assert result is not None
        assert result["set_cookies"] == []


class TestParseCookieExpiry:
    """_parse_cookie_expiry 从 Set-Cookie 解析过期时间。"""

    def test_parses_expires_http_date(self):
        """解析 expires= HTTP-date 格式。"""
        set_cookies = [
            "session=abc; Expires=Sat, 04 Jul 2026 16:25:38 GMT; HttpOnly"
        ]
        from datetime import datetime, timezone
        result = _parse_cookie_expiry(set_cookies)
        assert result is not None
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 4

    def test_parses_max_age(self):
        """解析 max-age= 相对秒数。"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        set_cookies = ["token=xyz; Max-Age=3600; Path=/"]
        result = _parse_cookie_expiry(set_cookies)
        assert result is not None
        delta = (result - now).total_seconds()
        assert 3500 < delta < 3700  # 约 3600 秒

    def test_earliest_expiry(self):
        """多个 Set-Cookie 时取最早过期时间。"""
        set_cookies = [
            "a=1; Max-Age=7200",     # 2 小时后过期
            "b=2; Max-Age=3600",     # 1 小时后过期
        ]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = _parse_cookie_expiry(set_cookies)
        assert result is not None
        delta = (result - now).total_seconds()
        assert 3500 < delta < 3700  # 取最早的 3600

    def test_empty_returns_none(self):
        assert _parse_cookie_expiry([]) is None

    def test_unparseable_returns_none(self):
        """无法解析的 Set-Cookie 返回 None。"""
        assert _parse_cookie_expiry(["no expiry info here"]) is None


class TestComputeCommonHeaders:
    """公共 Header 分析算法。"""

    def test_finds_invariant_headers(self):
        """多个请求中值相同的 Header 应被识别为公共头。"""
        raw = [
            {"url": "a", "method": "GET", "headers": {
                "Authorization": "Bearer xxx",
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://a.com/page1",
            }},
            {"url": "b", "method": "POST", "headers": {
                "Authorization": "Bearer xxx",
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://a.com/page2",
                "Content-Type": "application/json",
            }},
        ]
        result = _compute_common_headers(raw)
        assert "Authorization" in result
        assert "User-Agent" in result
        assert "Accept" in result
        # Referer 是动态的，除非所有请求相同
        assert "Referer" not in result
        # Content-Type 只出现在一个请求中，不到 50%
        assert "Content-Type" not in result

    def test_excludes_cookie(self):
        """Cookie 不应出现在公共 Header 中。"""
        raw = [
            {"url": "a", "method": "GET", "headers": {
                "Authorization": "Bearer xxx",
                "Cookie": "a=1; b=2",
            }},
            {"url": "b", "method": "GET", "headers": {
                "Authorization": "Bearer xxx",
                "Cookie": "a=1; b=2",
            }},
        ]
        result = _compute_common_headers(raw)
        assert "Authorization" in result
        assert "Cookie" not in result
        assert "cookie" not in result

    def test_empty_input(self):
        assert _compute_common_headers([]) == {}

    def test_single_request(self):
        """单个请求时返回全部非动态 Header（修复：单请求场景 threshold=1）。"""
        raw = [
            {"url": "a", "method": "GET", "headers": {
                "Authorization": "Bearer xxx",
                "User-Agent": "Mozilla/5.0",
            }},
        ]
        result = _compute_common_headers(raw)
        # 单请求时 threshold=1，全部非动态 headers 应被返回
        assert result["Authorization"] == "Bearer xxx"
        assert result["User-Agent"] == "Mozilla/5.0"

    def test_single_request_with_h2_pseudo_headers(self):
        """单个请求时过滤 HTTP/2 伪头部（:authority, :method 等）。"""
        raw = [
            {"url": "a", "method": "POST", "headers": {
                ":authority": "example.com",
                ":method": "POST",
                ":path": "/api/test",
                ":scheme": "https",
                "Authorization": "Bearer token123",
                "Apiclient": "saas-pc",
            }},
        ]
        result = _compute_common_headers(raw)
        # HTTP/2 伪头部应被过滤
        assert ":authority" not in result
        assert ":method" not in result
        assert ":path" not in result
        assert ":scheme" not in result
        # 业务头部应保留
        assert result["Authorization"] == "Bearer token123"
        assert result["Apiclient"] == "saas-pc"

    def test_skips_empty_values(self):
        raw = [
            {"url": "a", "method": "GET", "headers": {"X-Token": "  "}},
            {"url": "b", "method": "GET", "headers": {"X-Token": "  "}},
        ]
        result = _compute_common_headers(raw)
        assert "X-Token" not in result  # 空值被跳过


# ── Hostname 提取 + 域名匹配测试 ──────────────────────────────


class TestExtractHostname:
    """_extract_hostname 从 URL 文本中提取纯 hostname。"""

    def test_basic_http(self):
        assert _extract_hostname("https://example.com/api") == "example.com"

    def test_with_port(self):
        assert _extract_hostname("https://example.com:8080/path") == "example.com"

    def test_with_ws_protocol(self):
        assert _extract_hostname("wss://api.example.com/ws") == "api.example.com"

    def test_no_protocol(self):
        assert _extract_hostname("cdn.example.com/static/file.js") == "cdn.example.com"

    def test_uppercase(self):
        assert _extract_hostname("https://EXAMPLE.COM/") == "example.com"

    def test_empty(self):
        assert _extract_hostname("") == ""
        assert _extract_hostname(None) == ""


class TestIsSameOrSubdomain:
    """_is_same_or_subdomain 精确域名/子域名匹配。"""

    def test_exact_match(self):
        assert _is_same_or_subdomain("https://example.com/api", "example.com") is True

    def test_subdomain_match(self):
        assert _is_same_or_subdomain("https://api.example.com/data", "example.com") is True

    def test_multi_level_subdomain(self):
        assert _is_same_or_subdomain("https://cdn.static.example.com/x.js", "example.com") is True

    def test_no_false_match_similar_name(self):
        """不应匹配不是子域名的相似域名。"""
        assert _is_same_or_subdomain("https://notexample.com", "example.com") is False

    def test_no_false_match_suffix(self):
        """不应匹配后缀相同的域名。"""
        assert _is_same_or_subdomain("https://example.com.evil.org", "example.com") is False

    def test_path_contains_domain_string(self):
        """路径中包含域名字串不应被误匹配。"""
        assert _is_same_or_subdomain("https://other.com/api?d=example.com", "example.com") is False

    def test_case_insensitive(self):
        assert _is_same_or_subdomain("https://API.EXAMPLE.COM/", "example.com") is True

    def test_empty_input(self):
        assert _is_same_or_subdomain("", "example.com") is False
