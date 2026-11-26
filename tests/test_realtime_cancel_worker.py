"""验证 RealtimeCancelWorker 超时取消与扩展搜索逻辑。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from plugins.escort_driving.workers.realtime_cancel import RealtimeCancelWorker


def _make_realtime_task(
    created_seconds_ago: int,
) -> "EscortTask":
    from plugins.escort_driving.tasks import EscortTask

    task = EscortTask(
        demander_id="student1",
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="REALTIME",
    )
    # 回退 created_at 模拟下单时间
    task.created_at = datetime.utcnow() - timedelta(seconds=created_seconds_ago)
    # 实时单处于 published 状态等待抢单
    task.bind_event_bus(EventBus())
    task.publish_for_claim()
    return task


def _make_server_with_rules(timeout: int = 60, expand_after: int = 30) -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    server.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=timeout,
        updated_by="test",
        category="escort.cancel",
    )
    server.rule_config.set(
        key="escort.cancel.realtime.expand_after_seconds",
        value=expand_after,
        updated_by="test",
        category="escort.cancel",
    )
    return server


class _FakeWsManager:
    """记录广播消息的假 ws_manager。"""

    def __init__(self) -> None:
        self.broadcasts: list[dict] = []

    async def broadcast_to_online_coaches(self, message: dict) -> None:
        self.broadcasts.append(message)


@pytest.mark.asyncio
async def test_realtime_task_auto_cancelled_after_timeout():
    """超过 timeout_seconds 的实时单应被自动取消。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    # 下单 70 秒前，超过 60 秒超时
    task = _make_realtime_task(created_seconds_ago=70)
    server.task_repo.save(task)

    events: list = []
    server.event_bus.subscribe_all(lambda e: events.append(e))

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "cancelled"
    assert any(e.type == EventType.TASK_CANCELLED for e in events)


@pytest.mark.asyncio
async def test_realtime_task_not_cancelled_before_timeout():
    """未超时的实时单不应被取消。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    task = _make_realtime_task(created_seconds_ago=20)
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "published"


@pytest.mark.asyncio
async def test_realtime_task_expanded_search_after_expand_after():
    """超过 expand_after_seconds 未抢单应再次广播扩展邀请。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    fake_ws = _FakeWsManager()
    server.ws_manager = fake_ws
    # 下单 35 秒前，超过 30 秒扩展阈值，但未超过 60 秒超时
    task = _make_realtime_task(created_seconds_ago=35)
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    # 未被取消
    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "published"
    # 至少广播过一次扩展邀请
    expanded = [m for m in fake_ws.broadcasts if m.get("data", {}).get("expanded") is True]
    assert len(expanded) >= 1, "应广播扩展搜索邀请"
    # 验证坐标字段不为 None
    assert expanded[0]["data"]["origin_lat"] is not None
    assert expanded[0]["data"]["origin_lng"] is not None


@pytest.mark.asyncio
async def test_expand_search_only_once_per_task():
    """扩展搜索只广播一次（避免每个周期重复广播）。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    fake_ws = _FakeWsManager()
    server.ws_manager = fake_ws
    task = _make_realtime_task(created_seconds_ago=35)
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})
    await worker.run(context={"server": server})  # 第二个周期
    await worker.run(context={"server": server})  # 第三个周期

    expanded = [m for m in fake_ws.broadcasts if m.get("data", {}).get("expanded") is True]
    assert len(expanded) == 1, "扩展搜索只应广播一次"


@pytest.mark.asyncio
async def test_scheduled_task_not_affected_by_realtime_worker():
    """预约单（即使 published）不应被实时单取消 worker 影响。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    from plugins.escort_driving.tasks import EscortTask

    task = EscortTask(
        demander_id="student1",
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="SCHEDULED",
        scheduled_at=datetime.utcnow() + timedelta(hours=2),
    )
    task.created_at = datetime.utcnow() - timedelta(seconds=70)
    # 让预约单也进入 published 状态，验证 order_type 过滤而非状态过滤
    task.bind_event_bus(server.event_bus)
    task.publish_for_claim()
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "published"  # 预约单保持 published 状态，未被取消
