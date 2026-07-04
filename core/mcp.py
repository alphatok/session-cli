"""
MCP JSON-RPC 通信层 — 管理与 chrome-devtools-mcp 的交互。

支持:
    - Chrome 144+  autoConnect（默认，新授权握手）
    - 传统 CDP 端口（--browser-url）
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable, Dict, Optional

# ── 跨平台 npx 查找 ──────────────────────────────────────────

_NPX_CMD: Optional[str] = None

def _find_npx() -> Optional[str]:
    """在 Windows / Linux / macOS 上查找 npx 可执行文件。"""
    if os.name == "nt":
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs", "npx.cmd"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "nodejs", "npx.cmd"),
        ]
    else:
        candidates = ["/usr/local/bin/npx", "/usr/bin/npx"]
    for c in candidates:
        if os.path.isfile(c):
            return c
    # 兜底：PATH 查找
    return shutil.which("npx")


_NPX_CMD = _find_npx()


# ── JSON-RPC 通信 ────────────────────────────────────────────

def _jsonrpc_send(proc: subprocess.Popen, method: str, params: Optional[dict] = None) -> dict:
    """发送 JSON-RPC 请求，读取匹配 id 的响应（带超时）。"""
    request = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
        "method": method,
        "params": params or {},
    }
    payload = json.dumps(request) + "\n"

    try:
        proc.stdin.write(payload)
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        return {"error": f"Failed to write to MCP process: {e}"}

    deadline = time.time() + 30  # 30 秒超时
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.1)
            continue
        try:
            msg = json.loads(line)
            if msg.get("id") == request["id"]:
                return msg
        except json.JSONDecodeError:
            continue

    return {"error": f"Timeout waiting for response to '{method}'"}


def _start_mcp_server(auto_connect: bool = True, browser_url: Optional[str] = None) -> subprocess.Popen:
    """启动 chrome-devtools-mcp 进程并完成初始化握手。

    Args:
        auto_connect: 使用 Chrome 144+ autoConnect（默认 True）
        browser_url: 指定 CDP 浏览器 URL，仅在 auto_connect=False 时有效。
                     为 None 时默认使用 http://127.0.0.1:9222
    """
    if not _NPX_CMD:
        raise RuntimeError("未找到 npx，请安装 Node.js: https://nodejs.org")

    args = [_NPX_CMD, "-y", "chrome-devtools-mcp@latest"]
    if auto_connect:
        args.append("--autoConnect")
    else:
        args.append(f"--browser-url={browser_url or 'http://127.0.0.1:9222'}")

    nodejs_dir = os.path.dirname(_NPX_CMD)
    env = os.environ.copy()
    env["PATH"] = nodejs_dir + os.pathsep + env.get("PATH", "")

    proc = subprocess.Popen(
        ["cmd", "/c"] + args if os.name == "nt" else args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=env,
    )

    # MCP 初始化握手
    _jsonrpc_send(proc, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "session-cli", "version": "1.0.0"},
    })
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    proc.stdin.write(json.dumps(notification) + "\n")
    proc.stdin.flush()
    return proc


def _launch_temp_chrome(port: int = 9222) -> subprocess.Popen:
    """启动临时 Chrome 实例用于 CDP 调试。

    创建一个独立的临时 user-data-dir，不影响用户已有的 Chrome 会话。

    Args:
        port: Chrome 远程调试端口（默认 9222）

    Returns:
        subprocess.Popen 进程句柄

    Raises:
        RuntimeError: 找不到 Chrome 可执行文件
    """
    # 查找 Chrome 可执行文件
    if os.name == "nt":
        chrome_candidates = [
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
    else:
        chrome_candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]

    chrome_path = None
    for c in chrome_candidates:
        if os.path.isfile(c):
            chrome_path = c
            break

    if not chrome_path:
        chrome_path = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")

    if not chrome_path:
        raise RuntimeError("未找到 Chrome 浏览器，请安装 Google Chrome")

    # 创建临时 user-data-dir
    temp_dir = tempfile.mkdtemp(prefix="chrome_temp_")

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={temp_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "about:blank",
    ]

    proc = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 等待 Chrome 启动
    time.sleep(2)
    return proc


def _extract_result(resp: dict) -> str:
    """从 MCP tools/call 响应中提取文本内容。"""
    if "error" in resp:
        raise RuntimeError(f"MCP error: {resp['error']}")
    result = resp.get("result", {})
    if isinstance(result, dict):
        content = result.get("content", [])
        if isinstance(content, list) and content:
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    return item.get("text", "")
    return str(result)


def _extract_markdown_json(text: str) -> str:
    """从 evaluate_script 返回的 Markdown 中提取 JSON 文本值。

    格式示例:
        Script ran on page and returned:
        ```json
        "cookie1=val1; cookie2=val2"
        ```

    多种 fallback 策略确保鲁棒性。
    """
    if not isinstance(text, str):
        return ""

    # 策略 1: 匹配 ```json ... ``` 块中的双引号内容
    m = re.search(r'```(?:json)?\s*\n\s*"(.+?)"\s*\n```', text, re.DOTALL)
    if m:
        return m.group(1)

    # 策略 2: 在 markdown code block 内部查找所有内容
    m = re.search(r'```(?:json)?\s*\n(.+?)\n```', text, re.DOTALL)
    if m:
        content = m.group(1).strip().strip('"')
        return content

    # 策略 3: 去掉前缀 "Script ran..." 后提取第一个 JSON 字符串
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.rfind("```")
        if end > start:
            return text[start:end].strip().strip('"')

    # 策略 4: 直接返回去掉前缀的文本
    text = text.split("\n```json\n")[-1].split("\n```")[0].strip().strip('"')
    return text


# ── 认证凭据编码前缀 ──────────────────────────────────────────

AUTH_PREFIX = "__auth__"
"""Vault 中 auth token 条目的键名前缀，避免与真实 Cookie 名冲突。"""

HDR_PREFIX = "__hdr__"
"""Vault 中公共 Request Header 条目的键名前缀。"""

RAW_PREFIX = "__raw__"
"""Vault 中 raw_requests JSON blob 的键名前缀。"""

REL_PREFIX = "__rel__"
"""Vault 中 related_domains JSON blob 的键名前缀。"""

RAW_COOKIE_KEY = "__raw__cookie"
URL_KEY = "__original_url__"
"""Vault 中原始 cookie 字符串的键名。"""


class GrabCancelled(Exception):
    """抓取操作被取消（用户取消或超时）。"""
    pass


def _extract_markdown_json_obj(text: str) -> Optional[dict]:
    """从 evaluate_script 返回的 Markdown 中提取 JSON 对象。

    格式示例:
        Script ran on page and returned:
        ```json
        {"cookies": [...], "storage": {...}}
        ```

    Args:
        text: MCP evaluate_script 返回的 Markdown 文本

    Returns:
        解析后的 dict，失败时返回 None
    """
    if not isinstance(text, str):
        return None

    # 策略 1: 匹配 ```json ... ``` 块中的 JSON 对象（以 { 开头）
    m = re.search(r'```(?:json)?\s*\n(\{.+\})\s*\n```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 策略 2: 匹配 ```json ... ``` 块中的 JSON 对象（以 [ 开头）
    m = re.search(r'```(?:json)?\s*\n(\[.+\])\s*\n```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 策略 2.5: 匹配 ```json ... ``` 块中 double-encoded 的 JSON 字符串
    # evaluate_script 会将 JS 返回值 double-encode：
    #   JS 返回: {"cookies": [...]}
    #   MCP 包装: "{\"cookies\": [...]}"
    # 需要先解码外层字符串，再解析内层 JSON 对象
    m = re.search(r'```(?:json)?\s*\n\s*"(.+?)"\s*\n```', text, re.DOTALL)
    if m:
        try:
            inner = json.loads('"' + m.group(1) + '"')
            if isinstance(inner, str):
                obj = json.loads(inner)
                if isinstance(obj, dict):
                    return obj
        except (json.JSONDecodeError, Exception):
            pass

    # 策略 3: 提取文本中任意位置的 JSON 对象
    m = re.search(r'\{.+\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 策略 4: 提取文本中任意位置的 JSON 数组
    m = re.search(r'\[.+\]', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ── Network Request 解析器 ──────────────────────────────────


def _extract_hostname(url_text: str) -> str:
    """从任意文本中提取纯 hostname（小写，不含协议/端口/路径）。

    支持格式：
        - 纯 URL：https://example.com/api
        - Markdown 表格行：| 1 | GET | https://example.com/ | 200 |
        - wss://api.example.com:443/ws
    """
    if not isinstance(url_text, str):
        return ""

    text = url_text.strip().lower()
    # 如果文本不直接以协议开头，尝试用正则提取其中的 http(s):// URL
    if not any(text.startswith(p) for p in ("https://", "http://", "wss://", "ws://")):
        m = re.search(r'(?:https?|wss?)://[^\s|"\')\]>]+', text)
        if m:
            text = m.group(0)
        else:
            # 回退：尝试直接按路径分割
            text = text.split("/")[0].split(":")[0]
            text = text.strip('"').strip("'").strip()
            return text

    # 去掉协议前缀
    for prefix in ("https://", "http://", "wss://", "ws://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    # 去掉路径和端口
    text = text.split("/")[0].split(":")[0]
    # 去掉可能的引号
    text = text.strip('"').strip("'").strip()
    return text


def _is_same_or_subdomain(url_text: str, domain: str) -> bool:
    """检查 URL 文本的 hostname 是否等于 domain 或是其子域名。

    示例：
        _is_same_or_subdomain("https://example.com/api", "example.com") → True
        _is_same_or_subdomain("https://api.example.com", "example.com") → True
        _is_same_or_subdomain("https://cdn.static.example.com/x", "example.com") → True
        _is_same_or_subdomain("https://notexample.com", "example.com") → False
        _is_same_or_subdomain("https://example.com.evil.org", "example.com") → False
    """
    hostname = _extract_hostname(url_text)
    dom = domain.lower().strip()
    if not hostname or not dom:
        return False
    return hostname == dom or hostname.endswith("." + dom)


def _parse_network_list_table(text: str, domain: str) -> tuple[list[int], set[str]]:
    """解析 list_network_requests 返回的 Markdown 表格，提取目标域名 reqid + 全部 hostname。

    chrome-devtools-mcp 的 list_network_requests 返回格式示例:
        ## Network Requests
        Showing 1-30 of 50
        | ReqId | Method | URL | Status | Type |
        |-------|--------|-----|--------|------|
        | 3 | GET | https://example.com/api/me | 200 | XHR |
        | 4 | POST | https://other.com/analytics | 200 | XHR |

    Args:
        text: MCP 返回的 Markdown 文本
        domain: 目标域名（用于过滤 Header 分析请求）

    Returns:
        (reqids: 目标域名及其子域名的 reqid 列表,
         all_hostnames: 表格中所有请求的 hostname 去重集合)
    """
    if not isinstance(text, str):
        return [], set()

    reqids: list[int] = []
    all_hostnames: set[str] = set()
    in_table = False

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # 检测表格行（以 | 开头且包含 | 分隔符）
        if line.startswith("|") and "|" in line[1:]:
            # 跳过表头分隔行
            if re.match(r"^\|[\s\-:]+\|", line):
                in_table = True
                continue
            if in_table:
                # 提取全部 hostname（用于 related_domains）
                hostname = _extract_hostname(line)
                if hostname:
                    all_hostnames.add(hostname)

                # 目标域名匹配（用于 Header 分析）
                if _is_same_or_subdomain(line, domain):
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if parts and parts[0].isdigit():
                        reqids.append(int(parts[0]))
        else:
            if in_table and reqids:
                if not line.startswith("|"):
                    break

    return reqids, all_hostnames


def _parse_network_request_detail(text: str) -> Optional[dict]:
    """解析 get_network_request 返回的 Markdown 详细视图，提取 Request Headers。

    chrome-devtools-mcp 的 get_network_request 返回格式示例:
        ## Request #1
        URL: https://example.com/api/data
        Method: GET
        Status: 200

        ### Request Headers
        - Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx
        - User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...
        - Accept: application/json, text/plain, */*

        ### Response Headers
        - Content-Type: application/json

    Args:
        text: MCP 返回的 Markdown 文本

    Returns:
        {"url": str, "method": str, "headers": {key: value}} 或 None
    """
    if not isinstance(text, str):
        return None

    result: dict = {"url": "", "method": "GET", "headers": {}}

    # 提取 URL 和 Method
    url_m = re.search(r"URL:\s*(.+)", text)
    if url_m:
        result["url"] = url_m.group(1).strip()

    method_m = re.search(r"Method:\s*(\w+)", text)
    if method_m:
        result["method"] = method_m.group(1).strip()

    # 定位 Request Headers 区块
    in_req_headers = False
    for line in text.split("\n"):
        line_stripped = line.strip()

        if not in_req_headers:
            if "Request Headers" in line_stripped:
                in_req_headers = True
            continue

        # 检测区块结束（### Response Headers 或下一个 ### 标题 或 ---）
        if line_stripped.startswith("###") or line_stripped.startswith("---"):
            break

        # 解析 "- Key: Value" 或 "- Key: Value" 格式
        # 也支持 "* Key: Value" 或 tab 缩进格式
        m = re.match(r"[\-\*\t]\s*(.+?)\s*:\s*(.+)", line_stripped)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            if key and value:
                result["headers"][key] = value

    if not result["url"] and not result["headers"]:
        return None
    return result


def _compute_common_headers(raw_requests: list[dict]) -> dict[str, str]:
    """分析多个请求的 Header，提取跨请求"不变"的公共头。

    算法:
        1. 统计每个 Header 键在所有请求中出现的次数及值
        2. 若某个 Header 在 >=50% 的请求中出现且值完全相同 → 标记为"公共 Header"
        3. 优先关注非标准浏览器头（如 Authorization, X-*, Cookie 等）

    Args:
        raw_requests: [{"url", "method", "headers": {key: value}}] 列表

    Returns:
        {key: value} 公共 Header 字典
    """
    if not raw_requests:
        return {}

    total = len(raw_requests)
    threshold = max(total * 0.5, 2)  # 至少 2 个请求或 50%

    # 统计每个 Header 键在哪些请求中出现，对应的值是什么
    # key → {value: count, ...}
    header_stats: dict[str, dict[str, int]] = {}
    for req in raw_requests:
        for k, v in req.get("headers", {}).items():
            if k not in header_stats:
                header_stats[k] = {}
            header_stats[k][v] = header_stats[k].get(v, 0) + 1

    common: dict[str, str] = {}
    for key, value_counts in header_stats.items():
        # 找到出现最多的值
        best_value = max(value_counts, key=lambda k: value_counts[k])
        best_count = value_counts[best_value]

        # 跳过空值
        if not best_value or not best_value.strip():
            continue

        # 跳过一些高度动态的头
        dynamic_keys = {"referer", "origin", "host", "content-length", "content-type"}
        if key.lower().replace("-", "") in dynamic_keys:
            # 仅当值在 ALL 请求中相同才保留
            if best_count < total:
                continue

        if best_count >= threshold:
            common[key] = best_value

    # 排除 Cookie（Cookie 已在独立通道存储）
    common.pop("Cookie", None)
    common.pop("cookie", None)

    return common


def _grab_network_headers(
    proc,  # subprocess.Popen
    domain: str,
    on_progress: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    max_requests: int = 15,
) -> tuple[dict[str, str], list[dict], list[str]]:
    """通过 CDP Network 域抓取页面的 Request Headers + 关联域名。

    在页面加载后调用，捕获网络请求的 Request Headers 并分析公共头，
    同时收集所有被请求的域名作为 related_domains。

    Args:
        proc: 已初始化握手的 MCP subprocess.Popen 进程
        domain: 目标域名
        on_progress: 可选进度回调
        cancel_event: 可选取消事件
        max_requests: 最多分析的请求数（避免过多 JSON-RPC 调用）

    Returns:
        (common_headers: {key: value}, raw_requests: [...], related_domains: [str])
    """
    def _check_cancelled():
        if cancel_event and cancel_event.is_set():
            raise GrabCancelled("操作已被取消")

    def progress(stage: str, detail: str = ""):
        if on_progress:
            on_progress(stage, detail)

    _check_cancelled()
    progress("network_list", "获取网络请求列表...")

    # Step 1: 列出所有网络请求
    resp = _jsonrpc_send(proc, "tools/call", {
        "name": "list_network_requests",
        "arguments": {},
    })
    _check_cancelled()

    list_text = _extract_result(resp)
    reqids, all_hostnames = _parse_network_list_table(list_text, domain)

    # related_domains：全部请求的 hostname 去重排序
    related_domains: list[str] = sorted(all_hostnames)

    if not reqids:
        progress("network_done", f"未捕获到匹配的网络请求，发现 {len(related_domains)} 个关联域名")
        return {}, [], related_domains

    _check_cancelled()
    progress("network_capture", f"捕获到 {len(reqids)} 个请求，正在分析...")

    # Step 2: 逐个获取请求详情
    raw_requests: list[dict] = []
    analyzed = 0

    for reqid in reqids[:max_requests]:
        _check_cancelled()

        resp = _jsonrpc_send(proc, "tools/call", {
            "name": "get_network_request",
            "arguments": {"reqid": reqid},
        })
        _check_cancelled()

        detail_text = _extract_result(resp)
        detail = _parse_network_request_detail(detail_text)

        if detail and detail.get("url") and detail.get("headers"):
            # 再次确认 URL 属于目标域名或其子域名
            if _is_same_or_subdomain(detail["url"], domain):
                raw_requests.append({
                    "url": detail["url"],
                    "method": detail["method"],
                    "headers": detail["headers"],
                })
                analyzed += 1

    _check_cancelled()

    progress("network_done", f"捕获 {len(raw_requests)} 个原始请求, {len(related_domains)} 个关联域名")

    return {}, raw_requests, related_domains


# ── 增强版 Cookie + 凭据采集 JS 脚本 ───────────────────────────

_GRAB_JS = r"""() => {
    var result = {
        cookie: document.cookie || '',
        localStorage: {},
        sessionStorage: {}
    };

    // 采集所有 localStorage 条目
    try {
        for (var i = 0; i < localStorage.length; i++) {
            var key = localStorage.key(i);
            result.localStorage[key] = localStorage.getItem(key);
        }
    } catch (e) {}

    // 采集所有 sessionStorage 条目
    try {
        for (var i = 0; i < sessionStorage.length; i++) {
            var key = sessionStorage.key(i);
            result.sessionStorage[key] = sessionStorage.getItem(key);
        }
    } catch (e) {}

    return JSON.stringify(result);
}"""


# ── URL 重定向检测 ──────────────────────────────────────────

def _extract_current_url(text: str) -> Optional[str]:
    """从 navigate_page 返回的 Markdown 中提取当前页面 URL。

    导航返回格式示例:
        Successfully navigated to https://...
        ## Pages
        1: Page Title (https://actual-page-url) [selected]

    Args:
        text: navigate_page 返回的 Markdown 文本

    Returns:
        提取到的当前页面 URL，失败时返回 None
    """
    if not isinstance(text, str):
        return None
    # 匹配 (https?://...) 格式的 URL，取最后一个（当前选中页面的 URL）
    matches = re.findall(r'\(?(https?://[^\s)\]]+)\)?', text)
    if matches:
        return matches[-1].rstrip("/")
    return None


# ── Cookie 抓取核心 ──────────────────────────────────────────

def _grab_cookies_impl(
    proc,  # subprocess.Popen
    domain: str,
    on_progress: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    url: Optional[str] = None,
) -> dict:
    """在已连接的 MCP 进程上执行 Cookie + 认证凭据抓取。

    本函数不管理 MCP 进程生命周期，调用方负责提供已初始化的进程。

    Args:
        proc: 已初始化握手的 MCP subprocess.Popen 进程
        domain: 清理后的目标域名（用于页面匹配、Header 过滤、Vault 存储）
        on_progress: 可选进度回调
        cancel_event: 可选 threading.Event，外部 set 后中断本次抓取
        url: 可选，navigate_page 导航的完整 URL。为 None 时回退到 f"https://{domain}"

    Returns:
        {"cookies": Dict, "auth_tokens": List[dict], "headers": Dict, "raw_requests": List, "related_domains": List[str]}

    Raises:
        RuntimeError: Cookie 为空或通信失败
        GrabCancelled: 操作被外部取消
    """
    def progress(stage: str, detail: str = ""):
        if on_progress:
            on_progress(stage, detail)

    def _check_cancelled():
        if cancel_event and cancel_event.is_set():
            raise GrabCancelled("操作已被取消")

    # Step 1: 列出页面
    _check_cancelled()
    progress("listing", "获取页面列表...")
    resp = _jsonrpc_send(proc, "tools/call", {"name": "list_pages", "arguments": {}})
    _check_cancelled()
    pages_text = _extract_result(resp)

    # 从 Markdown 中匹配目标域名
    target_idx = None
    if isinstance(pages_text, str):
        for line in pages_text.split("\n"):
            if domain in line:
                m = re.match(r"(\d+):", line.strip())
                if m:
                    target_idx = int(m.group(1)) - 1
                    progress("found", f"找到页面 #{m.group(1)}")
                    break

    # Step 2: 选择页面（若存在）并刷新，确保 CDP 能捕获网络请求
    _check_cancelled()
    navigate_url = url if url else f"https://{domain}"
    if target_idx is not None:
        if target_idx > 0:
            progress("selecting", "切换到目标页面...")
            _jsonrpc_send(proc, "tools/call", {
                "name": "select_page",
                "arguments": {"pageIdx": target_idx},
            })
            _check_cancelled()
            time.sleep(1)
        # 关键：始终刷新页面，否则已打开的页面没有 CDP 网络记录
        progress("navigating", f"刷新页面 {navigate_url} ...")
        nav_resp = _jsonrpc_send(proc, "tools/call", {
            "name": "navigate_page",
            "arguments": {"type": "url", "url": navigate_url},
        })
    else:
        progress("navigating", f"导航到 {navigate_url} ...")
        nav_resp = _jsonrpc_send(proc, "tools/call", {
            "name": "navigate_page",
            "arguments": {"type": "url", "url": navigate_url},
        })

    _check_cancelled()
    time.sleep(5)

    # 检测页面是否被重定向到登录页（仅同域名内检测）
    nav_text = _extract_result(nav_resp)
    current_url = _extract_current_url(nav_text)
    if current_url and current_url != navigate_url.rstrip("/"):
        # 仅在同域名（或子域名）内才视为登录重定向，跨域跳转正常继续
        nav_host = _extract_hostname(navigate_url)
        cur_host = _extract_hostname(current_url)
        if nav_host == cur_host or cur_host.endswith("." + nav_host):
            raise RuntimeError(
                f"页面被重定向: {current_url}，请确认已在浏览器中登录该站点后重试"
            )

    # Step 3: 捕获网络请求 Request Headers（CDP Network 域）
    _check_cancelled()
    progress("network", "捕获网络请求头...")
    try:
        common_headers, raw_requests, related_domains = _grab_network_headers(
            proc, domain, on_progress=on_progress, cancel_event=cancel_event
        )
    except Exception:
        # 网络头捕获失败不阻塞主流程（Cookie 采集仍然进行）
        common_headers = {}
        raw_requests = []
        related_domains = []
        progress("network", "网络请求头捕获跳过（部分网站可能不支持）")

    # Step 4: 执行增强版 JS 采集 Cookie + localStorage + sessionStorage
    _check_cancelled()
    progress("evaluating", "采集 Cookie + 认证凭据...")
    resp = _jsonrpc_send(proc, "tools/call", {
        "name": "evaluate_script",
        "arguments": {"function": _GRAB_JS},
    })
    raw = _extract_result(resp)

    # 解析 JSON 对象
    data = _extract_markdown_json_obj(raw)

    if data is None:
        # 回退：尝试用旧版解析器处理 "name=value" 格式
        cookie_str = _extract_markdown_json(raw)
        if not cookie_str:
            raise RuntimeError("Cookie 为空，请确认已登录该站点")
        result: Dict[str, str] = {}
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                name, _, value = item.partition("=")
                if name:
                    result[name.strip()] = value
        progress("done", f"获取到 {len(result)} 个 Cookie")
        return {"cookies": result, "auth_tokens": [], "headers": common_headers, "raw_requests": raw_requests, "related_domains": related_domains}

    # 原始存取：直接取 cookie 字符串和全量 localStorage/sessionStorage
    raw_cookie = data.get("cookie", "") or ""
    raw_ls = data.get("localStorage", {}) or {}
    raw_ss = data.get("sessionStorage", {}) or {}

    # 构建 auth_tokens：所有 localStorage/sessionStorage 条目，原始存储
    auth_tokens: list = []
    for key, value in raw_ls.items():
        if value:
            auth_tokens.append({"source": "localStorage", "key": key, "value": value})
    for key, value in raw_ss.items():
        if value:
            auth_tokens.append({"source": "sessionStorage", "key": key, "value": value})

    progress("done", f"获取到 Cookie 原始字符串, {len(auth_tokens)} 个存储凭据, {len(common_headers)} 个公共 Header, {len(related_domains)} 个关联域名")
    return {"cookies": raw_cookie, "auth_tokens": auth_tokens, "headers": common_headers, "raw_requests": raw_requests, "related_domains": related_domains}


def grab_cookies(
    domain: str,
    auto_connect: bool = True,
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> dict:
    """通过 chrome-devtools-mcp 抓取指定域名的 Cookie（每次独立启动进程）。

    CLI 路径使用此函数；Web 路径请使用 core.mcp_manager.grab_cookies_managed。

    Args:
        domain: 目标域名或完整 URL，如 "yuanbao.tencent.com" 或 "https://example.com/path"
        auto_connect: 使用 Chrome 144+ autoConnect（默认 True）
        on_progress: 可选回调 (stage: str, detail: str) -> None

    Returns:
        {"cookies": Dict, "auth_tokens": List[dict]}

    Raises:
        RuntimeError: 连接失败或未登录
    """
    raw_input = domain.strip()
    # 提取纯 domain（用于 Vault 存储 key、页面匹配、Header 过滤）
    clean_domain = raw_input.lower().replace("https://", "").replace("http://", "").split("/")[0]
    # 构建导航 URL：如果用户提供了完整 URL 则使用原值，否则补全 https://
    navigate_url = raw_input if raw_input.startswith("http") else f"https://{clean_domain}"

    def progress(stage: str, detail: str = ""):
        if on_progress:
            on_progress(stage, detail)

    proc = None
    try:
        proc = _start_mcp_server(auto_connect=auto_connect)
        if auto_connect:
            progress("waiting", "等待 Chrome 授权，请在弹窗中点击 Allow")
        time.sleep(5)

        return _grab_cookies_impl(proc, clean_domain, on_progress=on_progress, url=navigate_url)

    finally:
        if proc:
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
