"""轻量 asyncio 调度器服务。

在 FastAPI lifespan 中启动，周期性执行注册的 worker（如取消策略 worker）。
worker 需实现 `async def run(self, context) -> None` 接口。
单个 worker 抛异常会被捕获并记录，不影响其他 worker 或后续周期。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Worker(Protocol):
    """调度器 worker 协议。"""

    name: str

    async def run(self, context: Any) -> None:
        """执行一次周期任务。context 由 SchedulerService.start 传入。"""
        ...


class SchedulerService:
    """周期性调度器。

    Args:
        interval_seconds: 调度间隔（秒），默认 1.0。
    """

    def __init__(self, interval_seconds: float = 1.0) -> None:
        self._interval = interval_seconds
        self._workers: list[Worker] = []
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    def register(self, worker: Worker) -> None:
        """注册 worker。"""
        self._workers.append(worker)

    async def start(self, context: Any = None) -> None:
        """启动调度循环（阻塞直至 stop 被调用）。"""
        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            for worker in self._workers:
                try:
                    await worker.run(context)
                except Exception:
                    logger.exception(
                        "worker %s 执行异常", getattr(worker, "name", worker)
                    )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass  # 超时即进入下一周期

    async def stop(self) -> None:
        """停止调度循环。幂等。"""
        if self._stop_event is not None:
            self._stop_event.set()
