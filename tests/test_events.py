"""测试事件总线。"""

from __future__ import annotations

from umcp_core.events import EventBus, Event, EventType


class TestEventBus:
    def test_publish_and_subscribe(self):
        bus = EventBus()
        received: list[Event] = []

        bus.subscribe(EventType.TASK_PUBLISHED, lambda e: received.append(e))

        event = Event(
            type=EventType.TASK_PUBLISHED,
            source_layer="L2",
            payload={"task_id": "t1"},
        )
        bus.publish(event)

        assert len(received) == 1
        assert received[0].type == EventType.TASK_PUBLISHED
        assert received[0].payload["task_id"] == "t1"

    def test_subscribe_all(self):
        bus = EventBus()
        all_events: list[Event] = []
        bus.subscribe_all(lambda e: all_events.append(e))

        bus.publish(Event(type=EventType.TASK_PUBLISHED, source_layer="L2"))
        bus.publish(Event(type=EventType.PAYMENT_HELD, source_layer="L4"))

        assert len(all_events) == 2

    def test_unsubscribe(self):
        bus = EventBus()
        received: list[Event] = []

        def handler(e: Event) -> None:
            received.append(e)

        bus.subscribe(EventType.TASK_PUBLISHED, handler)
        bus.unsubscribe(EventType.TASK_PUBLISHED, handler)

        bus.publish(Event(type=EventType.TASK_PUBLISHED, source_layer="L2"))
        assert len(received) == 0

    def test_history(self):
        bus = EventBus()
        bus.publish(Event(type=EventType.TASK_PUBLISHED, source_layer="L2"))
        bus.publish(Event(type=EventType.TASK_ASSIGNED, source_layer="L3"))

        history = bus.history()
        assert len(history) == 2
        assert history[0].type == EventType.TASK_PUBLISHED
        assert history[1].type == EventType.TASK_ASSIGNED

    def test_handler_exception_does_not_block(self):
        bus = EventBus()
        successful: list[Event] = []

        def bad_handler(e: Event) -> None:
            raise RuntimeError("故意出错")

        def good_handler(e: Event) -> None:
            successful.append(e)

        bus.subscribe(EventType.TASK_PUBLISHED, bad_handler)
        bus.subscribe(EventType.TASK_PUBLISHED, good_handler)

        # 不应抛出
        bus.publish(Event(type=EventType.TASK_PUBLISHED, source_layer="L2"))
        assert len(successful) == 1

    def test_event_type_from_string(self):
        event = Event(type="task.published", source_layer="L2")
        assert event.type == EventType.TASK_PUBLISHED

    def test_clear(self):
        bus = EventBus()
        bus.publish(Event(type=EventType.TASK_PUBLISHED, source_layer="L2"))
        assert len(bus.history()) == 1
        bus.clear()
        assert len(bus.history()) == 0
