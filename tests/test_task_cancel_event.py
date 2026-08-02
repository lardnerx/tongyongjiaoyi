"""验证 Task.cancel() 发布 TASK_CANCELLED 事件（而非 TASK_COMPLETED）。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import Task, TaskStatus
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType


class _TestTask(Task):
    def task_type(self) -> str:
        return "test"


def _collect_events(bus: EventBus) -> list:
    events: list = []
    bus.subscribe_all(lambda e: events.append(e))
    return events


def test_cancel_emits_task_cancelled_event():
    """cancel() 应发布 TASK_CANCELLED 事件。"""
    bus = EventBus()
    events = _collect_events(bus)

    task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
    task.bind_event_bus(bus)
    task.publish_for_claim()
    events.clear()

    task.cancel()

    assert task.status == TaskStatus.CANCELLED
    assert any(e.type == EventType.TASK_CANCELLED for e in events), \
        "cancel() 应发布 TASK_CANCELLED 事件"
    assert not any(e.type == EventType.TASK_COMPLETED for e in events), \
        "cancel() 不应发布 TASK_COMPLETED 事件"
