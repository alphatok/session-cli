"""
MCP 长连接管理器 — 复用 chrome-devtools-mcp 进程，避免每次抓取都重新启动。

特性:
    - 单例模式，全局唯一 MCP 进程
    - 线程安全通信锁（串行化 stdin/stdout 访问）
    - 10 分钟空闲自动断开（后台监控线程）
    - 手动连接/断开 API
    - 状态查询（connected / idle_seconds / uptime）

使用:
    from core.mcp_manager import McpManager, grab_cookies_managed

    mgr = McpManager.get_instance()
    mgr.connect()
    data = grab_cookies_managed("example.com")
    mgr.disconnect()
"""

from __future__ import annotations

import time
import threading
from typing import Optional, Dict

from core.mcp import (
    _start_mcp_server,
    _grab_cookies_impl,
)


# ── McpManager 单例 ────────────────────────────────────────────

class McpManager:
    """MCP 进程生命周期管理器（单例）。"""

    _instance: Optional["McpManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._proc: Optional[any] = None  # subprocess.Popen
        self._comm_lock = threading.Lock()  # 串行化 stdin/stdout 访问
        self._last_activity: float = 0.0
        self._connected_at: float = 0.0
        self._idle_timeout: float = 600.0  # 10 分钟
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_running: bool = False

    @classmethod
    def get_instance(cls) -> "McpManager":
        """获取全局单例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 连接管理 ──────────────────────────────────────────────

    def connect(self) -> bool:
        """启动 MCP 进程并完成初始化握手。

        Returns:
            True 表示连接成功
        """
        with self._comm_lock:
            # 如果已连接则先断开
            if self._proc is not None:
                self._disconnect_internal()

            try:
                self._proc = _start_mcp_server(auto_connect=True)
            except RuntimeError as e:
                self._proc = None
                raise RuntimeError(f"MCP 连接失败: {e}") from e

            now = time.time()
            self._last_activity = now
            self._connected_at = now
            self._start_monitor()
            return True

    def disconnect(self):
        """断开 MCP 进程连接。"""
        with self._comm_lock:
            self._disconnect_internal()
            self._stop_monitor()

    def _disconnect_internal(self):
        """内部断开（调用方需持有 _comm_lock）。"""
        if self._proc is None:
            return
        try:
            self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
        self._last_activity = 0.0
        self._connected_at = 0.0

    def ensure_connected(self):
        """确保 MCP 已连接（幂等操作）。"""
        if not self.is_connected():
            self.connect()
        # 等待 Chrome 授权（首次 autoConnect 需用户点击 Allow）
        time.sleep(2)

    # ── 状态查询 ──────────────────────────────────────────────

    def is_connected(self) -> bool:
        """检查 MCP 进程是否存活。"""
        return self._proc is not None and self._proc.poll() is None

    def get_status(self) -> dict:
        """获取连接状态详情。

        Returns:
            {
                "connected": bool,
                "idle_seconds": float,    # 距上次操作已过多少秒
                "uptime_seconds": float,   # 本次连接已持续多少秒（未连接时为 0）
                "timeout_seconds": float,  # 空闲超时阈值（秒）
            }
        """
        now = time.time()
        connected = self.is_connected()
        return {
            "connected": connected,
            "idle_seconds": round(now - self._last_activity, 1) if connected else 0,
            "uptime_seconds": round(now - self._connected_at, 1) if connected else 0,
            "timeout_seconds": self._idle_timeout,
        }

    # ── 活动追踪 ──────────────────────────────────────────────

    def _bump_activity(self):
        """更新最近活动时间戳（每次抓取操作后调用）。"""
        self._last_activity = time.time()

    # ── 空闲监控 ──────────────────────────────────────────────

    def _start_monitor(self):
        """启动后台空闲监控线程（每 30 秒检查一次）。"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_running = True
        self._monitor_thread = threading.Thread(
            target=self._idle_monitor_loop,
            daemon=True,
            name="mcp-idle-monitor",
        )
        self._monitor_thread.start()

    def _stop_monitor(self):
        """停止空闲监控线程。"""
        self._monitor_running = False

    def _idle_monitor_loop(self):
        """后台循环：检测空闲超时或进程意外退出。"""
        while self._monitor_running:
            time.sleep(30)
            if not self._monitor_running:
                break
            # 进程意外退出
            if self._proc is not None and self._proc.poll() is not None:
                self.disconnect()
                break
            # 空闲超时
            if time.time() - self._last_activity > self._idle_timeout:
                self.disconnect()
                break

    # ── 通信接口（供 grab_cookies_managed 使用）───────────────

    def get_proc(self):
        """获取当前 MCP 进程句柄（外部只读）。"""
        return self._proc

    def acquire_comm_lock(self):
        """获取通信锁（上下文管理器使用）。"""
        return self._comm_lock


# ── 模块级便捷函数 ─────────────────────────────────────────────

def grab_cookies_managed(
    domain: str,
    on_progress=None,
) -> dict:
    """通过 McpManager 复用进程抓取 Cookie + 认证凭据。

    与 mcp.grab_cookies() 返回相同格式，但使用长连接复用 MCP 进程。

    Args:
        domain: 目标域名
        on_progress: 可选回调 (stage, detail)

    Returns:
        {"cookies": Dict, "auth_tokens": List[dict]}

    Raises:
        RuntimeError: 连接失败或未登录
    """
    mgr = McpManager.get_instance()

    with mgr.acquire_comm_lock():
        # 确保已连接（幂等）
        if not mgr.is_connected():
            mgr.connect()
            time.sleep(5)  # 等待 Chrome 授权
            if not mgr.is_connected():
                raise RuntimeError("MCP 连接失败")

        proc = mgr.get_proc()
        if proc is None:
            raise RuntimeError("MCP 进程不可用")

        # 清理域名
        domain = domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]

        try:
            result = _grab_cookies_impl(proc, domain, on_progress=on_progress)
            mgr._bump_activity()
            return result
        except Exception:
            # 抓取异常时标记进程不可用，下次自动重连
            mgr._disconnect_internal()
            raise
