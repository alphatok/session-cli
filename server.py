"""
Session Manager Web UI — FastAPI

uv run python main.py serve
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import queue

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

import core

# ── Templates ─────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── SSE 进度管理 ──────────────────────────────────────────────

_progress_queues: dict[str, queue.Queue] = {}
_progress_lock = threading.Lock()


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
    """后台线程执行 cookie 抓取，通过 queue 汇报进度。"""
    q = _get_or_create_queue(task_id)

    def on_progress(stage, detail):
        q.put(json.dumps({"stage": stage, "detail": detail}))

    try:
        cookies = core.grab_cookies(domain, auto_connect=True, on_progress=on_progress)
        if not cookies:
            q.put(json.dumps({"stage": "error", "detail": "未获取到 Cookie，请确认已登录"}))
            _cleanup_queue(task_id)
            return
        core.store_site(domain, cookies)
        q.put(json.dumps({"stage": "completed", "detail": f"成功存储 {len(cookies)} 个 Cookie", "count": len(cookies)}))
    except Exception as e:
        q.put(json.dumps({"stage": "error", "detail": str(e)}))
    finally:
        _cleanup_queue(task_id)


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭时管理 Vault 生命周期。"""
    try:
        vault = core.get_vault()
        vault.list_sessions()  # 验证 vault 可用
        print("[✓] Vault 已解锁（keyring 自动获取密码）")
    except Exception as e:
        print(f"[!] Vault 解锁失败: {e}")
        print("[!] 请先执行: uv run python main.py init")
    yield
    # 清理：关闭所有 SSE 队列
    with _progress_lock:
        _progress_queues.clear()


app = FastAPI(title="Session Manager", version="2.0", lifespan=lifespan)


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
        while True:
            try:
                msg = q.get(timeout=0.1)
                yield f"data: {msg}\n\n"
                data = json.loads(msg)
                if data.get("stage") in ("completed", "error"):
                    break
            except queue.Empty:
                yield ": keepalive\n\n"
                await asyncio.sleep(0.5)

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
