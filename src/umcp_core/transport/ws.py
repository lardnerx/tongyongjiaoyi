"""WebSocket 连接管理器 + EventBus→WS 桥接。"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

from umcp_core.core.base import User
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType


# 仅推送业务事件，不推内部桥接事件
WS_PUSHABLE_EVENTS: set[EventType] = {
    EventType.TASK_PUBLISHED,
    EventType.TASK_ASSIGNED,
    EventType.TASK_COMPLETED,
    EventType.TASK_CANCELLED,
    EventType.RESOURCE_REGISTERED,
    EventType.RESOURCE_STATUS_CHANGED,
    EventType.DEAL_CREATED,
    EventType.DEAL_PAID,
    EventType.DEAL_COMPLETED,
    EventType.DEAL_DISPUTED,
    EventType.SUBTASK_COMPLETED,
    EventType.SUBTASK_CANCELLED,
    EventType.TRUST_UPDATED,
    EventType.ANOMALY_DETECTED,
    EventType.DISPUTE_OPENED,
}


class ConnectionManager:
    """按 user_id 维护活跃 WebSocket 连接（多端同步）。"""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = threading.RLock()

    async def connect(self, ws: WebSocket, user: User) -> None:
        """接受连接并注册到 user_id 索引。"""
        await ws.accept()
        with self._lock:
            self._connections.setdefault(user.user_id, set()).add(ws)

    async def disconnect(self, ws: WebSocket, user: User) -> None:
        """移除指定连接。"""
        with self._lock:
            conns = self._connections.get(user.user_id)
            if conns:
                conns.discard(ws)
                if not conns:
                    del self._connections[user.user_id]

    async def send_to_user(self, user_id: str, message: dict[str, Any]) -> None:
        """推送给指定用户的所有活跃连接。推送失败的连接被清理。"""
        with self._lock:
            conns = list(self._connections.get(user_id, []))
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            with self._lock:
                conns_set = self._connections.get(user_id)
                if conns_set:
                    for ws in dead:
                        conns_set.discard(ws)
                    if not conns_set:
                        self._connections.pop(user_id, None)

    async def disconnect_all(self) -> None:
        """关闭所有连接（应用停止时调用）。"""
        with self._lock:
            all_conns = list(self._connections.values())
            self._connections.clear()
        for conns in all_conns:
            for ws in conns:
                try:
                    await ws.close()
                except Exception:
                    pass


def _extract_user_ids(event: Event) -> list[str]:
    """从事件 payload 提取关联 user_id。

    当前支持 task 事件的 demander_id 字段。
    deal/resource 事件的 payload 在领域模型未发事件时不会触发此函数。
    """
    ids: list[str] = []
    payload = event.payload or {}
    if "demander_id" in payload:
        ids.append(payload["demander_id"])
    if "supplier_id" in payload:
        ids.append(payload["supplier_id"])
    if "user_id" in payload:
        ids.append(payload["user_id"])
    return list(dict.fromkeys(ids))  # 去重保序


def _format_ws_message(event: Event) -> dict[str, Any]:
    """构造 WS 推送消息。"""
    ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
    return {
        "type": event.type.value,
        "timestamp": ts,
        "data": event.payload or {},
    }


def make_ws_event_bridge(
    manager: ConnectionManager,
    loop: asyncio.AbstractEventLoop,
) -> Callable[[Event], None]:
    """构造 EventBus → WebSocket 桥接函数。

    EventBus 是同步调用，WebSocket 是异步推送。用 run_coroutine_threadsafe
    把推送投递到主事件循环。
    """

    def _bridge(event: Event) -> None:
        if event.type not in WS_PUSHABLE_EVENTS:
            return
        user_ids = _extract_user_ids(event)
        if not user_ids:
            return
        message = _format_ws_message(event)
        for uid in user_ids:
            asyncio.run_coroutine_threadsafe(
                manager.send_to_user(uid, message),
                loop,
            )

    return _bridge
