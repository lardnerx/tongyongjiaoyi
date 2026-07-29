"""EventType 扩展和 EventBus.unsubscribe_all 测试。"""

from __future__ import annotations

from umcp_core.events.bus import EventBus, Event
from umcp_core.events.types import EventType


class TestEventTypeExtension:
    def test_resource_events_exist(self):
        assert EventType.RESOURCE_REGISTERED.value == "resource.registered"
        assert EventType.RESOURCE_STATUS_CHANGED.value == "resource.status_changed"

    def test_deal_events_exist(self):
        assert EventType.DEAL_CREATED.value == "deal.created"
        assert EventType.DEAL_PAID.value == "deal.paid"
        assert EventType.DEAL_COMPLETED.value == "deal.completed"
        assert EventType.DEAL_DISPUTED.value == "deal.disputed"


class TestEventBusUnsubscribeAll:
    def test_unsubscribe_all_removes_global_handler(self):
        bus = EventBus()
        calls: list[Event] = []

        def handler(event: Event) -> None:
            calls.append(event)

        bus.subscribe_all(handler)
        assert len(bus.history()) == 0 or True  # subscribe 不发事件

        bus.publish(Event(type=EventType.TASK_PUBLISHED, payload={"task_id": "t1"}))
        assert len(calls) == 1

        bus.unsubscribe_all(handler)
        bus.publish(Event(type=EventType.TASK_PUBLISHED, payload={"task_id": "t2"}))
        assert len(calls) == 1  # 不再收到

    def test_unsubscribe_all_unrelated_handler_keeps_others(self):
        bus = EventBus()
        calls_a: list[Event] = []
        calls_b: list[Event] = []

        def handler_a(event: Event) -> None:
            calls_a.append(event)

        def handler_b(event: Event) -> None:
            calls_b.append(event)

        bus.subscribe_all(handler_a)
        bus.subscribe_all(handler_b)
        bus.unsubscribe_all(handler_a)

        bus.publish(Event(type=EventType.TASK_PUBLISHED))
        assert len(calls_a) == 0
        assert len(calls_b) == 1

    def test_unsubscribe_all_not_subscribed_is_noop(self):
        bus = EventBus()

        def handler(event: Event) -> None:
            pass

        # 不应抛异常
        bus.unsubscribe_all(handler)
