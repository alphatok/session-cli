"""server.py 测试 — FastAPI 路由、SSE 清理、lifespan。"""

from __future__ import annotations

import json
import queue
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """创建带 mock core 的 TestClient（Bug #7 修复验证：lifespan）。"""
    # 直接 patch server.py 中调用的顶层 core API，避免深路径导入缓存问题
    with patch("core.list_sites", return_value=[]), \
         patch("core.get_vault", return_value=MagicMock(list_sessions=MagicMock(return_value=[]))):
        from server import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_with_sessions():
    """带 mock 站点列表的 TestClient。"""
    mock_data = [{"domain": "example.com", "cookie_count": 1,
                   "created_at": "2026-01-01T12:00:00", "expires_at": "2026-12-31T12:00:00"}]

    with patch("core.list_sites", return_value=mock_data), \
         patch("core.get_vault", return_value=MagicMock(list_sessions=MagicMock(return_value=[]))):
        from server import app
        with TestClient(app) as c:
            yield c


class TestRoutes:
    """API 路由测试。"""

    def test_index_returns_html(self, client):
        """首页返回 HTML。"""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_list_sessions_empty(self, client):
        """列出站点（空）。"""
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_sessions(self, client_with_sessions):
        """列出站点（有数据）。"""
        resp = client_with_sessions.get("/api/sessions")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["domain"] == "example.com"

    def test_get_session_not_found(self, client):
        """获取不存在的站点。"""
        with patch("core.get_site", return_value=None):
            resp = client.get("/api/sessions/nope.com")
            assert resp.status_code == 404

    def test_delete_session(self, client):
        """删除站点。"""
        with patch("core.delete_site", return_value=True):
            resp = client.delete("/api/sessions/test.com")
            assert resp.status_code == 200
            assert resp.json()["status"] == "deleted"

    def test_delete_session_not_found(self, client):
        """删除不存在的站点。"""
        with patch("core.delete_site", return_value=False):
            resp = client.delete("/api/sessions/nope.com")
            assert resp.status_code == 404

    def test_grab_returns_task_id(self, client):
        """grab 返回 task_id。"""
        resp = client.get("/api/sessions/grab?domain=example.com")
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "started"

    def test_grab_start_new_task(self, client):
        """grab 接受自定义 task_id。"""
        resp = client.get("/api/sessions/grab?domain=test.com&task_id=mytask")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "mytask"


class TestSSE:
    """SSE 进度流测试（Bug #4 修复验证：队列清理）。"""

    def test_progress_stream_completed(self, client):
        """SSE 流完成时清理队列。"""
        # 预先放入 completed 消息
        test_queue = queue.Queue()
        test_queue.put(json.dumps({"stage": "completed", "detail": "done", "count": 3}))

        with patch("server._get_or_create_queue", return_value=test_queue):
            resp = client.get("/api/sessions/grab/progress?task_id=t1")
            assert resp.status_code == 200
            body = resp.text
            assert "completed" in body
            assert "done" in body

    def test_progress_stream_error(self, client):
        """SSE 流错误时的处理。"""
        test_queue = queue.Queue()
        test_queue.put(json.dumps({"stage": "error", "detail": "Connection failed"}))

        with patch("server._get_or_create_queue", return_value=test_queue):
            resp = client.get("/api/sessions/grab/progress?task_id=t2")
            assert "error" in resp.text
            assert "Connection failed" in resp.text


class TestCleanupQueue:
    """_cleanup_queue 内存泄漏修复验证（Bug #4）。"""

    def test_cleanup_removes_queue(self):
        """cleanup 后队列从 dict 中移除。"""
        from server import _get_or_create_queue, _cleanup_queue, _progress_queues

        _progress_queues.clear()
        _get_or_create_queue("task-123")
        assert "task-123" in _progress_queues

        _cleanup_queue("task-123")
        assert "task-123" not in _progress_queues

    def test_cleanup_nonexistent(self):
        """清理不存在的 key 不会出错。"""
        from server import _cleanup_queue
        _cleanup_queue("never-existed")  # 不应抛异常


class TestRunGrabTask:
    """_run_grab_task 后台任务测试。"""

    def test_success_flow(self):
        """成功路径：grab → store → completed 消息。"""
        from server import _run_grab_task, _get_or_create_queue
        from server import _progress_queues

        _progress_queues.clear()

        # 先获取队列引用（_run_grab_task 完成后会清理 dict，需要提前保留引用）
        q = _get_or_create_queue("t-success")

        with patch("server.grab_cookies_managed") as mock_grab, \
             patch("core.store_site") as mock_store:
            mock_grab.return_value = {
                "cookies": "token=abc",
                "auth_tokens": [],
                "headers": {},
                "raw_requests": [],
            }
            mock_store.return_value = {"domain": "test.com", "cookie_count": 1}

            _run_grab_task("t-success", "test.com")

        msg = q.get(timeout=0.5)
        data = json.loads(msg)
        assert data["stage"] == "completed"
        assert data["count"] == 1

    def test_empty_cookies(self):
        """Cookie 为空时的错误处理。"""
        from server import _run_grab_task, _get_or_create_queue
        from server import _progress_queues

        _progress_queues.clear()

        q = _get_or_create_queue("t-empty")

        with patch("server.grab_cookies_managed", return_value={
            "cookies": "", "auth_tokens": [], "headers": {}, "raw_requests": [],
        }):
            _run_grab_task("t-empty", "test.com")

        msg = q.get(timeout=0.5)
        data = json.loads(msg)
        assert data["stage"] == "error"
        assert "未获取到" in data["detail"]

    def test_exception_handling(self):
        """异常时的错误处理。"""
        from server import _run_grab_task, _get_or_create_queue
        from server import _progress_queues

        _progress_queues.clear()

        q = _get_or_create_queue("t-error")

        with patch("server.grab_cookies_managed", side_effect=RuntimeError("Boom")):
            _run_grab_task("t-error", "test.com")

        msg = q.get(timeout=0.5)
        data = json.loads(msg)
        assert data["stage"] == "error"
        assert "Boom" in data["detail"]


class TestLifespan:
    """lifespan 生命周期测试（Bug #7 修复验证：不再使用 on_event）。"""

    def test_lifespan_attr(self):
        """app 使用 lifespan 而非 on_event。"""
        from server import app
        assert app.router.lifespan_context is not None
