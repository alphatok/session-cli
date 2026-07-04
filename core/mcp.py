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


def _start_mcp_server(auto_connect: bool = True) -> subprocess.Popen:
    """启动 chrome-devtools-mcp 进程并完成初始化握手。"""
    if not _NPX_CMD:
        raise RuntimeError("未找到 npx，请安装 Node.js: https://nodejs.org")

    args = [_NPX_CMD, "-y", "chrome-devtools-mcp@latest"]
    if auto_connect:
        args.append("--autoConnect")
    else:
        args.append("--browser-url=http://127.0.0.1:9222")

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


# ── 增强版 Cookie + 凭据采集 JS 脚本 ───────────────────────────

_GRAB_JS = r"""() => {
    var result = {
        cookies: [],
        storage: {localStorage: {}, sessionStorage: {}}
    };

    // ── 1. 采集所有 document.cookie ──
    if (document.cookie) {
        var pairs = document.cookie.split(';');
        for (var i = 0; i < pairs.length; i++) {
            var p = pairs[i].trim();
            if (!p) continue;
            var eq = p.indexOf('=');
            if (eq > 0) {
                result.cookies.push({
                    name: p.substring(0, eq),
                    value: p.substring(eq + 1)
                });
            }
        }
    }

    // ── 2. 认证相关关键词模式 ──
    var patterns = [
        'token', 'auth', 'jwt', 'bearer', 'access', 'refresh',
        'session', 'id_token', 'api_key', 'apikey', 'secret',
        'credential', 'authorization', 'csrf', 'xsrf', '_csrf',
        '_token', 'oauth', 'sso', 'login', 'key', 'pass'
    ];

    function isAuthKey(k) {
        var lower = k.toLowerCase();
        for (var i = 0; i < patterns.length; i++) {
            if (lower.indexOf(patterns[i]) !== -1) return true;
        }
        return false;
    }

    // ── 3. 扫描 localStorage ──
    try {
        for (var i = 0; i < localStorage.length; i++) {
            var key = localStorage.key(i);
            if (isAuthKey(key)) {
                result.storage.localStorage[key] = localStorage.getItem(key);
            }
        }
    } catch (e) {}

    // ── 4. 扫描 sessionStorage ──
    try {
        for (var i = 0; i < sessionStorage.length; i++) {
            var key = sessionStorage.key(i);
            if (isAuthKey(key)) {
                result.storage.sessionStorage[key] = sessionStorage.getItem(key);
            }
        }
    } catch (e) {}

    return JSON.stringify(result);
}"""


# ── Cookie 抓取核心 ──────────────────────────────────────────

def _grab_cookies_impl(
    proc,  # subprocess.Popen
    domain: str,
    on_progress: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    """在已连接的 MCP 进程上执行 Cookie + 认证凭据抓取。

    本函数不管理 MCP 进程生命周期，调用方负责提供已初始化的进程。

    Args:
        proc: 已初始化握手的 MCP subprocess.Popen 进程
        domain: 清理后的目标域名
        on_progress: 可选进度回调
        cancel_event: 可选 threading.Event，外部 set 后中断本次抓取

    Returns:
        {"cookies": Dict, "auth_tokens": List[dict]}

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

    # Step 2: 选择或导航
    _check_cancelled()
    if target_idx is not None:
        if target_idx > 0:
            progress("selecting", "切换到目标页面...")
            _jsonrpc_send(proc, "tools/call", {
                "name": "select_page",
                "arguments": {"pageIdx": target_idx},
            })
            _check_cancelled()
            time.sleep(1)
    else:
        progress("navigating", f"导航到 https://{domain} ...")
        _jsonrpc_send(proc, "tools/call", {
            "name": "navigate_page",
            "arguments": {"type": "url", "url": f"https://{domain}"},
        })
        _check_cancelled()
        time.sleep(5)

    # Step 3: 执行增强版 JS 采集 Cookie + localStorage + sessionStorage
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
        return {"cookies": result, "auth_tokens": []}

    # 提取 Cookie 名值对
    cookies: Dict[str, str] = {}
    for c in data.get("cookies", []):
        if isinstance(c, dict) and "name" in c:
            cookies[c["name"]] = c.get("value", "")

    # 提取认证凭据
    auth_tokens: list = []
    storage = data.get("storage", {})
    for source, label in [("localStorage", "ls"), ("sessionStorage", "ss")]:
        for key, value in storage.get(source, {}).items():
            if value:
                auth_tokens.append({
                    "source": source,
                    "key": key,
                    "value": value,
                })

    progress("done", f"获取到 {len(cookies)} 个 Cookie, {len(auth_tokens)} 个认证凭据")
    return {"cookies": cookies, "auth_tokens": auth_tokens}


def grab_cookies(
    domain: str,
    auto_connect: bool = True,
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> dict:
    """通过 chrome-devtools-mcp 抓取指定域名的 Cookie（每次独立启动进程）。

    CLI 路径使用此函数；Web 路径请使用 core.mcp_manager.grab_cookies_managed。

    Args:
        domain: 目标域名，如 "yuanbao.tencent.com"
        auto_connect: 使用 Chrome 144+ autoConnect（默认 True）
        on_progress: 可选回调 (stage: str, detail: str) -> None

    Returns:
        {"cookies": Dict, "auth_tokens": List[dict]}

    Raises:
        RuntimeError: 连接失败或未登录
    """
    domain = domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]

    def progress(stage: str, detail: str = ""):
        if on_progress:
            on_progress(stage, detail)

    proc = None
    try:
        proc = _start_mcp_server(auto_connect=auto_connect)
        if auto_connect:
            progress("waiting", "等待 Chrome 授权，请在弹窗中点击 Allow")
        time.sleep(5)

        return _grab_cookies_impl(proc, domain, on_progress=on_progress)

    finally:
        if proc:
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
