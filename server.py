"""
Session Manager Web UI — FastAPI

uv run python main.py serve
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import queue

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.types import ASGIApp, Receive, Scope, Send

import core
from core.mcp_manager import McpManager, grab_cookies_managed

# ── Templates ─────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── SSE 进度管理 ──────────────────────────────────────────────

_progress_queues: dict[str, queue.Queue] = {}
_progress_lock = threading.Lock()

# 活跃任务追踪（用于取消操作）
_active_tasks: dict[str, threading.Event] = {}  # task_id → cancel_event
_active_tasks_lock = threading.Lock()

# 全局关闭信号（用于 SSE 生成器退出 + lifespan 清理）
_shutdown_event = threading.Event()

# ── 全局日志 ─────────────────────────────────────────────────

_log_queue: queue.Queue = queue.Queue()
_log_history: list = []  # 最多保留 200 条
_log_lock = threading.Lock()
_MAX_LOG_HISTORY = 200


def _emit_log(stage: str, detail: str):
    """发送日志到所有输出通道：console、日志队列、历史记录。"""
    global _log_history
    entry = {"stage": stage, "detail": detail, "time": time.strftime("%H:%M:%S")}
    # 1. Console
    print(f"[{entry['time']}] [{stage}] {detail}")
    # 2. 日志队列（SSE 推送）
    _log_queue.put(entry)
    # 3. 历史记录
    with _log_lock:
        _log_history.append(entry)
        if len(_log_history) > _MAX_LOG_HISTORY:
            _log_history = _log_history[-_MAX_LOG_HISTORY:]


def _get_or_create_queue(task_id: str) -> queue.Queue:
    with _progress_lock:
        if task_id not in _progress_queues:
            _progress_queues[task_id] = queue.Queue()
        return _progress_queues[task_id]


def _cleanup_queue(task_id: str) -> None:
    """任务完成后清理队列，防止内存泄漏。"""
    with _progress_lock:
        _progress_queues.pop(task_id, None)


def _run_grab_task(task_id: str, domain: str):
    """后台线程执行 cookie 抓取（通过 McpManager 长连接）。"""
    q = _get_or_create_queue(task_id)
    cancel_event = threading.Event()

    # 注册任务
    with _active_tasks_lock:
        _active_tasks[task_id] = cancel_event

    def on_progress(stage, detail):
        q.put(json.dumps({"stage": stage, "detail": detail}))
        _emit_log(stage, detail)

    _emit_log("task", f"开始抓取: {domain}")
    try:
        data = grab_cookies_managed(domain, on_progress=on_progress, cancel_event=cancel_event)
        cookies = data.get("cookies", "")
        auth_tokens = data.get("auth_tokens", [])
        headers = data.get("headers", {})
        raw_requests = data.get("raw_requests", [])
        related_domains = data.get("related_domains", [])
        cookie_count = cookies.count(";") + 1 if cookies else 0
        if not cookies and not auth_tokens and not headers:
            msg = "未获取到 Cookie、认证凭据和请求头，请确认已登录"
            q.put(json.dumps({"stage": "error", "detail": msg}))
            _emit_log("error", msg)
            return
        # 提取纯 domain 用于 Vault 存储 key
        store_domain = domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
        core.store_site(store_domain, data, original_url=domain)
        parts = []
        if headers or raw_requests:
            parts.append(f"{len(headers)} 个公共 Header, {len(raw_requests)} 个原始请求")
        if related_domains:
            parts.append(f"{len(related_domains)} 个关联域名")
        hdr_msg = (", " + ", ".join(parts)) if parts else ""
        q.put(json.dumps({
            "stage": "completed",
            "detail": f"成功存储 {cookie_count} 个 Cookie, {len(auth_tokens)} 个认证凭据{hdr_msg}",
            "count": cookie_count,
            "auth_count": len(auth_tokens),
            "header_count": len(headers),
            "raw_request_count": len(raw_requests),
            "related_domain_count": len(related_domains),
        }))
        _emit_log("completed", f"抓取完成: {domain} ({cookie_count} cookies, {len(auth_tokens)} tokens)")
    except Exception as e:
        msg = str(e)
        if cancel_event.is_set():
            q.put(json.dumps({"stage": "cancelled", "detail": msg}))
            _emit_log("cancelled", msg)
        else:
            q.put(json.dumps({"stage": "error", "detail": msg}))
            _emit_log("error", msg)
    finally:
        # 清理
        with _active_tasks_lock:
            _active_tasks.pop(task_id, None)
        _cleanup_queue(task_id)


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭时管理 Vault + MCP 生命周期。"""
    # 重置关闭信号（从上一次运行的残留中恢复）
    _shutdown_event.clear()
    try:
        vault = core.get_vault()
        vault.list_sessions()  # 验证 vault 可用
        print("[✓] Vault 已解锁（keyring 自动获取密码）")
        _emit_log("system", "Vault 已解锁")
    except Exception as e:
        print(f"[!] Vault 解锁失败: {e}")
        print("[!] 请先执行: uv run python main.py init")
        _emit_log("error", f"Vault 解锁失败: {e}")
    try:
        yield
    except (GeneratorExit, asyncio.CancelledError):
        # Ctrl+C 触发的关闭，正常流程
        pass
    finally:
        print("[*] 正在关闭服务...")
        # 1. 先通知 SSE 生成器退出，取消活跃任务
        _shutdown_event.set()
        with _active_tasks_lock:
            for evt in _active_tasks.values():
                evt.set()
            _active_tasks.clear()
        # 2. 等待 SSE 生成器优雅退出（可被 cancel 打断，不影响后续清理）
        try:
            await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            pass
        # 3. 清理 SSE 队列
        with _progress_lock:
            _progress_queues.clear()
        # 4. 终止 MCP 进程（直接 kill，避免阻塞在锁上）
        try:
            mgr = McpManager.get_instance()
            if mgr.is_connected():
                proc = mgr._proc
                if proc is not None:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
                    try:
                        proc.kill()
                    except Exception:
                        pass
                mgr._proc = None
                mgr._stop_monitor()
                print("[✓] MCP 连接已关闭")
        except Exception:
            pass
        print("[✓] 服务已关闭")


# ── Graceful shutdown middleware ──────────────────────────────

class _GracefulShutdownMiddleware:
    """拦截 SSE 连接在关闭时的 CancelledError，只打 WARN 日志。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except asyncio.CancelledError:
            _emit_log("warn", "SSE 连接未关闭（服务正在停止，属正常行为）")


app = FastAPI(title="Session Manager", version="2.0", lifespan=lifespan)
app.add_middleware(_GracefulShutdownMiddleware)


# ── Routes ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页面。"""
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/sessions")
async def api_list_sessions():
    """列出所有站点。"""
    try:
        sites = core.list_sites()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return sites


@app.get("/api/sessions/grab")
async def api_grab(domain: str = Query(...), task_id: Optional[str] = Query(None)):
    """开始抓取 Session（返回 task_id 用于 SSE 进度订阅）。"""
    import uuid
    task_id = task_id or uuid.uuid4().hex[:8]

    try:
        core.get_vault()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    thread = threading.Thread(target=_run_grab_task, args=(task_id, domain), daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "started"}


@app.get("/api/sessions/grab/progress")
async def api_grab_progress(task_id: str = Query(...)):
    """SSE 流式推送抓取进度。"""
    q = _get_or_create_queue(task_id)

    async def event_stream():
        try:
            while not _shutdown_event.is_set():
                try:
                    msg = await asyncio.to_thread(q.get, True, 0.05)
                    yield f"data: {msg}\n\n"
                    data = json.loads(msg)
                    if data.get("stage") in ("completed", "error", "cancelled"):
                        break
                except queue.Empty:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # uvicorn 关闭时正常 cancel SSE 连接
            pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/sessions/{domain}")
async def api_get_session(domain: str):
    """获取站点详情。"""
    site = core.get_site(domain)
    if site is None:
        return JSONResponse({"error": "未找到"}, status_code=404)
    return site


@app.delete("/api/sessions/{domain}")
async def api_delete_session(domain: str):
    """删除站点。"""
    ok = core.delete_site(domain)
    if not ok:
        return JSONResponse({"error": "未找到"}, status_code=404)
    return {"status": "deleted", "domain": domain}


@app.post("/api/sessions/{domain}/refresh")
async def api_refresh_session(domain: str):
    """立即更新指定站点的 Session（重新抓取并覆盖）。"""
    import uuid

    try:
        core.get_vault()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    # 使用原始 URL（如果存储过），否则回退到域名
    site = core.get_site(domain)
    target_url = (site.get("original_url") if site and site.get("original_url") else domain) if site else domain

    task_id = uuid.uuid4().hex[:8]
    thread = threading.Thread(target=_run_grab_task, args=(task_id, target_url), daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "started", "domain": domain}


@app.post("/api/sessions/grab/{task_id}/cancel")
async def api_cancel_grab(task_id: str):
    """取消正在进行的抓取/刷新任务。"""
    with _active_tasks_lock:
        cancel_event = _active_tasks.get(task_id)
        if cancel_event is None:
            return JSONResponse({"error": "任务不存在或已完成"}, status_code=404)
        cancel_event.set()
    return {"status": "cancelling", "task_id": task_id}


# ── 日志 API ────────────────────────────────────────────────

@app.get("/api/logs/recent")
async def api_logs_recent():
    """返回最近日志列表。"""
    with _log_lock:
        return list(_log_history)


@app.get("/api/logs/stream")
async def api_logs_stream():
    """SSE 流式推送日志。"""
    async def event_stream():
        try:
            # 先发送历史日志
            with _log_lock:
                for entry in _log_history:
                    yield f"data: {json.dumps(entry)}\n\n"
            # 持续推送新日志
            while not _shutdown_event.is_set():
                try:
                    entry = await asyncio.to_thread(_log_queue.get, True, 0.1)
                    yield f"data: {json.dumps(entry)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # uvicorn 关闭时正常 cancel SSE 连接
            pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── MCP 连接管理 ─────────────────────────────────────────────

@app.get("/api/mcp/status")
async def api_mcp_status():
    """获取 MCP 连接状态。"""
    mgr = McpManager.get_instance()
    return mgr.get_status()


@app.post("/api/mcp/connect")
async def api_mcp_connect(browser_mode: str = Query("user")):
    """手动连接 MCP（含 CDP 健康检查）。

    Args:
        browser_mode: "user" 使用用户已登录的浏览器，"temp" 启动临时浏览器
    """
    mgr = McpManager.get_instance()
    if mgr.is_connected():
        ok, msg = mgr.health_check()
        if ok:
            _emit_log("mcp", "MCP 已连接（复用现有连接）")
            return {"status": "already_connected", "cdp_status": msg, "browser_mode": mgr.get_status().get("browser_mode")}
        else:
            # CDP 已断开，尝试重连
            _emit_log("mcp", "CDP 连接丢失，重新连接中...")
            mgr.disconnect()
    try:
        _emit_log("mcp", f"正在连接 MCP（{'临时浏览器' if browser_mode == 'temp' else '用户浏览器'}）...")
        mgr.connect(browser_mode=browser_mode)
        _emit_log("mcp", "MCP 连接成功")
        return {"status": "connected", "cdp_status": "CDP 连接正常", "browser_mode": browser_mode}
    except RuntimeError as e:
        _emit_log("error", f"MCP 连接失败: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/mcp/disconnect")
async def api_mcp_disconnect():
    """手动断开 MCP。"""
    mgr = McpManager.get_instance()
    if not mgr.is_connected():
        return {"status": "not_connected"}
    mgr.disconnect()
    _emit_log("mcp", "MCP 已断开")
    return {"status": "disconnected"}
