"""事件总线。"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Callable

from umcp_core.events.types import EventType


class Event:
    """事件对象。"""

    def __init__(
        self,
        type: EventType | str,
        source_layer: str = "",
        payload: dict[str, Any] | None = None,
        timestamp: float | None = None,
        event_id: str | None = None,
    ) -> None:
        self.type: EventType = type if isinstance(type, EventType) else EventType(type)
        self.source_layer: str = source_layer
        self.payload: dict[str, Any] = payload or {}
        self.timestamp: float = timestamp if timestamp is not None else time.time()
        self.event_id: str = event_id or f"evt_{int(self.timestamp * 1000)}_{id(self)}"

    def __repr__(self) -> str:
        return f"<Event {self.type.value} layer={self.source_layer} payload_keys={list(self.payload)}>"


EventHandler = Callable[[Event], None]


class EventBus:
    """事件总线（同步内存实现，线程安全）。

    生产环境可替换为 Kafka/Pulsar 等异步实现。
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []
        self._lock = threading.RLock()
        self._history: list[Event] = []

    def publish(self, event: Event) -> None:
        """发布事件，同步触发所有订阅者。"""
        with self._lock:
            self._history.append(event)
            handlers = list(self._handlers.get(event.type, [])) + list(self._global_handlers)

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                # 处理器异常不应阻塞总线，记录后继续
                import sys

                print(f"[EventBus] 处理器异常: {e}", file=sys.stderr)

    def subscribe(self, type_: EventType, handler: EventHandler) -> None:
        """订阅特定类型的事件。"""
        with self._lock:
            self._handlers[type_].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """订阅所有事件（用于审计日志、L7 规则引擎等）。"""
        with self._lock:
            self._global_handlers.append(handler)

    def unsubscribe(self, type_: EventType, handler: EventHandler) -> None:
        with self._lock:
            if handler in self._handlers[type_]:
                self._handlers[type_].remove(handler)

    def handler_count(self, event_type: EventType) -> int:
        """返回指定事件类型的订阅 handler 数量（不含 global handler）。"""
        with self._lock:
            return len(self._handlers.get(event_type, []))

    def history(self) -> list[Event]:
        """返回事件历史快照（用于回放、调试）。"""
        with self._lock:
            return list(self._history)

    def clear(self) -> None:
        with self._lock:
            self._history.clear()


class InMemoryEventBus(EventBus):
    """显式命名的内存事件总线实现，便于配置注入。"""

    pass
