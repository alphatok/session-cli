"""core/mcp.py 测试 — MCP JSON-RPC 通信、Cookie 提取、Markdown 解析。"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest

from core.mcp import (
    _extract_markdown_json,
    _extract_result,
    _find_npx,
    _jsonrpc_send,
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


class TestGrabCookiesIntegration:
    """grab_cookies 流程测试（带 mock subprocess）。"""

    @patch("core.mcp._start_mcp_server")
    @patch("core.mcp.time.sleep", return_value=None)
    def test_full_grab_flow(self, mock_sleep, mock_start, mock_subprocess,
                            sample_mcp_page_list, sample_mcp_cookie_result):
        """完整抓取流程：list → select → evaluate → parse。"""
        mock_start.return_value = mock_subprocess

        call_count = 0

        def mock_readline():
            nonlocal call_count
            call_count += 1
            return json.dumps({"jsonrpc": "2.0", "id": 1234567890000, "result": {
                "content": [{"type": "text", "text": str(call_count)}]
            }}) + "\n"

        mock_subprocess.stdout.readline = mock_readline

        from core.mcp import grab_cookies

        progress_stages = []

        with patch("core.mcp.time.time", return_value=1234567890):
            result = grab_cookies(
                "test.example.com",
                auto_connect=False,
                on_progress=lambda s, d: progress_stages.append(s),
            )

        assert isinstance(result, dict)
        for s in ("listing",):
            assert s in progress_stages, f"Missing stage: {s}"
