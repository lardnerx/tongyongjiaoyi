"""验证 SchedulerService 调度器框架。"""
from __future__ import annotations

import asyncio

import pytest

from umcp_core.transport.scheduler import SchedulerService


class _CountingWorker:
    """计数 worker，记录被调用次数。"""

    def __init__(self, name: str = "counter"):
        self.name = name
        self.call_count = 0
        self.last_context = None

    async def run(self, context) -> None:
        self.call_count += 1
        self.last_context = context


@pytest.mark.asyncio
async def test_scheduler_runs_workers_periodically():
    """调度器应按间隔周期调用 worker。"""
    scheduler = SchedulerService(interval_seconds=0.05)
    worker = _CountingWorker()
    scheduler.register(worker)

    task = asyncio.create_task(scheduler.start(context={"server": "fake"}))
    await asyncio.sleep(0.18)  # 约 3-4 个周期
    await scheduler.stop()
    await task

    assert worker.call_count >= 3, f"应至少调用 3 次，实际 {worker.call_count}"
    assert worker.last_context == {"server": "fake"}


@pytest.mark.asyncio
async def test_scheduler_stop_is_idempotent():
    """stop 应可重复调用。"""
    scheduler = SchedulerService(interval_seconds=0.1)
    worker = _CountingWorker()
    scheduler.register(worker)

    task = asyncio.create_task(scheduler.start(context=None))
    await asyncio.sleep(0.05)
    await scheduler.stop()
    await scheduler.stop()  # 不应抛异常
    await task


@pytest.mark.asyncio
async def test_scheduler_worker_exception_does_not_crash_loop():
    """单个 worker 抛异常不应影响其他 worker 与后续周期。"""
    class _BoomWorker:
        name = "boom"

        async def run(self, context) -> None:
            raise RuntimeError("boom")

    scheduler = SchedulerService(interval_seconds=0.05)
    boom = _BoomWorker()
    counter = _CountingWorker()
    scheduler.register(boom)
    scheduler.register(counter)

    task = asyncio.create_task(scheduler.start(context=None))
    await asyncio.sleep(0.15)
    await scheduler.stop()
    await task

    assert counter.call_count >= 2, "异常 worker 不应阻断其他 worker"
