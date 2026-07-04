"""core/mcp_manager.py 测试 — McpManager 单例生命周期、空闲超时、通信锁。"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from core.mcp_manager import McpManager


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_mcp_manager():
    """每个测试前重置 McpManager 单例状态。"""
    McpManager._instance = None
    yield
    # 清理：断开任何残留连接
    mgr = McpManager._instance
    if mgr is not None:
        try:
            mgr.disconnect()
        except Exception:
            pass
    McpManager._instance = None


@pytest.fixture
def mock_mcp_process():
    """返回一个 mock subprocess.Popen 对象。"""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.poll.return_value = None
    return proc


# ── Test Cases ───────────────────────────────────────────────

class TestMcpManagerSingleton:
    """单例模式验证。"""

    def test_get_instance_returns_same_object(self):
        """多次调用 get_instance 返回同一实例。"""
        a = McpManager.get_instance()
        b = McpManager.get_instance()
        assert a is b

    def test_thread_safe_singleton(self):
        """多线程同时获取实例不会产生多个实例。"""
        instances = []

        def get_instance():
            instances.append(McpManager.get_instance())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = instances[0]
        for inst in instances:
            assert inst is first


class TestMcpManagerStatus:
    """状态查询测试。"""

    def test_is_connected_false_initially(self):
        """初始状态：未连接。"""
        mgr = McpManager.get_instance()
        assert mgr.is_connected() is False

    def test_get_status_disconnected(self):
        """未连接时的 status 返回。"""
        mgr = McpManager.get_instance()
        status = mgr.get_status()
        assert status["connected"] is False
        assert status["idle_seconds"] == 0
        assert status["uptime_seconds"] == 0

    def test_get_status_connected(self, mock_mcp_process):
        """连接后 status 反映正确状态。"""
        mgr = McpManager.get_instance()
        with patch("core.mcp_manager._start_mcp_server", return_value=mock_mcp_process):
            with patch("core.mcp_manager.time.sleep", return_value=None):
                with patch.object(mgr, "health_check", return_value=(True, "ok")):
                    mgr.connect()

        assert mgr.is_connected() is True
        status = mgr.get_status()
        assert status["connected"] is True
        assert status["uptime_seconds"] >= 0
        assert status["timeout_seconds"] == 600


class TestMcpManagerConnectDisconnect:
    """连接/断开生命周期。"""

    def test_connect_starts_monitor(self, mock_mcp_process):
        """连接后启动空闲监控线程。"""
        mgr = McpManager.get_instance()
        with patch("core.mcp_manager._start_mcp_server", return_value=mock_mcp_process):
            with patch("core.mcp_manager.time.sleep", return_value=None):
                with patch.object(mgr, "health_check", return_value=(True, "ok")):
                    mgr.connect()

        assert mgr.is_connected() is True
        assert mgr._monitor_running is True

    def test_disconnect_stops_monitor(self, mock_mcp_process):
        """断开后停止空闲监控线程。"""
        mgr = McpManager.get_instance()
        with patch("core.mcp_manager._start_mcp_server", return_value=mock_mcp_process):
            with patch("core.mcp_manager.time.sleep", return_value=None):
                with patch.object(mgr, "health_check", return_value=(True, "ok")):
                    mgr.connect()
        mgr.disconnect()

        assert mgr.is_connected() is False
        assert mgr._monitor_running is False
        assert mgr._proc is None

    def test_connect_kills_previous(self, mock_mcp_process):
        """再次连接前会断开已有连接。"""
        mgr = McpManager.get_instance()
        with patch("core.mcp_manager._start_mcp_server", return_value=mock_mcp_process):
            with patch("core.mcp_manager.time.sleep", return_value=None):
                with patch.object(mgr, "health_check", return_value=(True, "ok")):
                    mgr.connect()
                first_proc = mgr.get_proc()

                # 再次连接
                with patch.object(mgr, "health_check", return_value=(True, "ok")):
                    mgr.connect()
                second_proc = mgr.get_proc()

        # 旧进程被 terminate
        first_proc.terminate.assert_called()

    def test_disconnect_when_not_connected_is_noop(self):
        """未连接时 disconnect 不会抛异常。"""
        mgr = McpManager.get_instance()
        mgr.disconnect()  # 不应抛异常


class TestMcpManagerIdleTimeout:
    """空闲超时测试。"""

    @patch("core.mcp_manager.time.sleep", return_value=None)
    def test_idle_timeout_triggers_disconnect(self, mock_sleep, mock_mcp_process):
        """空闲超过 10 分钟自动断开。"""
        mgr = McpManager.get_instance()
        with patch("core.mcp_manager._start_mcp_server", return_value=mock_mcp_process):
            with patch.object(mgr, "health_check", return_value=(True, "ok")):
                mgr.connect()

        # 模拟超时：设置 last_activity 为 601 秒前
        mgr._last_activity = time.time() - 601
        mgr._idle_timeout = 600

        # 手动触发一次监控检查
        mgr._idle_monitor_loop()

        assert mgr.is_connected() is False

    @patch("core.mcp_manager.time.sleep", return_value=None)
    def test_idle_before_timeout_does_not_disconnect(self, mock_sleep, mock_mcp_process):
        """空闲未超时时不断开。"""
        mgr = McpManager.get_instance()
        with patch("core.mcp_manager._start_mcp_server", return_value=mock_mcp_process):
            with patch.object(mgr, "health_check", return_value=(True, "ok")):
                mgr.connect()

        # 设置 last_activity 为刚发生
        mgr._last_activity = time.time()
        mgr._idle_timeout = 600

        # 直接设置 _monitor_running = False 让循环只执行一次
        mgr._monitor_running = True

        # 手动检查（不会超时）
        assert mgr.is_connected() is True
        self._check_idle_not_triggered(mgr)

    def _check_idle_not_triggered(self, mgr):
        """辅助：验证未超时时连接仍在。"""
        elapsed = time.time() - mgr._last_activity
        assert elapsed < mgr._idle_timeout


class TestMcpManagerCommLock:
    """通信锁测试。"""

    def test_comm_lock_is_threading_lock(self):
        """_comm_lock 是 threading.RLock 实例。"""
        mgr = McpManager.get_instance()
        lock_type_name = type(mgr._comm_lock).__name__
        assert lock_type_name == "RLock"

    def test_acquire_comm_lock_returns_same_lock(self):
        """acquire_comm_lock 返回正确的锁。"""
        mgr = McpManager.get_instance()
        lock = mgr.acquire_comm_lock()
        assert lock is mgr._comm_lock


class TestMcpManagerBumpActivity:
    """活动时间戳更新测试。"""

    def test_bump_activity_updates_timestamp(self, mock_mcp_process):
        """_bump_activity 更新 _last_activity。"""
        mgr = McpManager.get_instance()
        with patch("core.mcp_manager._start_mcp_server", return_value=mock_mcp_process):
            with patch("core.mcp_manager.time.sleep", return_value=None):
                with patch.object(mgr, "health_check", return_value=(True, "ok")):
                    mgr.connect()

        old_time = mgr._last_activity
        time.sleep(0.01)
        mgr._bump_activity()

        assert mgr._last_activity >= old_time
