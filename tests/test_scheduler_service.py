"""验证 SchedulerService 调度器框架。"""
from __future__ import annotations

import asyncio

import pytest

from umcp_core.transport.scheduler import SchedulerService


class _CountingWorker:
    """计数 worker，达到目标调用次数后设置事件。"""

    def __init__(self, name: str = "counter", target: int = 3) -> None:
        self.name = name
        self.call_count = 0
        self.last_context = None
        self.target = target
        self.done_event: asyncio.Event | None = None

    async def run(self, context) -> None:
        self.call_count += 1
        self.last_context = context
        if self.done_event is not None and self.call_count >= self.target:
            self.done_event.set()


@pytest.mark.asyncio
async def test_scheduler_runs_workers_periodically():
    """调度器应按间隔周期调用 worker。"""
    scheduler = SchedulerService(interval_seconds=0.05)
    worker = _CountingWorker(target=3)
    done = asyncio.Event()
    worker.done_event = done
    scheduler.register(worker)

    task = asyncio.create_task(scheduler.start(context={"server": "fake"}))
    # 等待 worker 达到 3 次调用，或超时
    await asyncio.wait_for(done.wait(), timeout=2.0)
    await scheduler.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert worker.call_count >= 3, f"应至少调用 3 次，实际 {worker.call_count}"
    assert worker.last_context == {"server": "fake"}


@pytest.mark.asyncio
async def test_scheduler_stop_is_idempotent():
    """stop 应可重复调用。"""
    scheduler = SchedulerService(interval_seconds=0.1)
    worker = _CountingWorker(target=1)
    done = asyncio.Event()
    worker.done_event = done
    scheduler.register(worker)

    task = asyncio.create_task(scheduler.start(context=None))
    await asyncio.wait_for(done.wait(), timeout=2.0)
    await scheduler.stop()
    await scheduler.stop()  # 不应抛异常
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_scheduler_worker_exception_does_not_crash_loop():
    """单个 worker 抛异常不应影响其他 worker 与后续周期。"""
    class _BoomWorker:
        name = "boom"

        async def run(self, context) -> None:
            raise RuntimeError("boom")

    scheduler = SchedulerService(interval_seconds=0.05)
    boom = _BoomWorker()
    counter = _CountingWorker(target=2)
    done = asyncio.Event()
    counter.done_event = done
    scheduler.register(boom)
    scheduler.register(counter)

    task = asyncio.create_task(scheduler.start(context=None))
    await asyncio.wait_for(done.wait(), timeout=2.0)
    await scheduler.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert counter.call_count >= 2, "异常 worker 不应阻断其他 worker"


@pytest.mark.asyncio
async def test_stop_before_start_is_noop():
    """start 之前调用 stop 应为静默 no-op。"""
    scheduler = SchedulerService(interval_seconds=0.1)
    await scheduler.stop()  # 不应抛异常


@pytest.mark.asyncio
async def test_restart_after_stop():
    """stop 后可重新 start。"""
    scheduler = SchedulerService(interval_seconds=0.05)
    worker = _CountingWorker(target=1)
    done1 = asyncio.Event()
    worker.done_event = done1
    scheduler.register(worker)

    # 第一次 start
    task1 = asyncio.create_task(scheduler.start(context=None))
    await asyncio.wait_for(done1.wait(), timeout=2.0)
    await scheduler.stop()
    await asyncio.wait_for(task1, timeout=2.0)
    first_count = worker.call_count

    # 第二次 start（重启）
    done2 = asyncio.Event()
    worker.done_event = done2
    worker.target = first_count + 1
    task2 = asyncio.create_task(scheduler.start(context=None))
    await asyncio.wait_for(done2.wait(), timeout=2.0)
    await scheduler.stop()
    await asyncio.wait_for(task2, timeout=2.0)

    assert worker.call_count > first_count, "重启后应继续调用 worker"
