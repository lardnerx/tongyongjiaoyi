"""ConnectionManager 单元测试。"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.transport.ws import (
    ConnectionManager,
    WS_PUSHABLE_EVENTS,
    _extract_user_ids,
    _format_ws_message,
    make_ws_event_bridge,
)


def _make_user(user_id: str = "u1") -> User:
    provider = PhoneAuthProvider()
    user = provider.authenticate(Credential("phone", "13800000000"))
    user.user_id = user_id
    return user


def _make_ws(user_id: str = "u1") -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.client_state = MagicMock()
    return ws


class TestConnectionManagerConnect:
    @pytest.mark.asyncio
    async def test_connect_registers_by_user_id(self):
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws = _make_ws()
        await mgr.connect(ws, user)
        assert "u1" in mgr._connections
        assert ws in mgr._connections["u1"]

    @pytest.mark.asyncio
    async def test_connect_multiple_devices_same_user(self):
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect(ws1, user)
        await mgr.connect(ws2, user)
        assert len(mgr._connections["u1"]) == 2


class TestConnectionManagerDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self):
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws = _make_ws()
        await mgr.connect(ws, user)
        await mgr.disconnect(ws, user)
        assert "u1" not in mgr._connections

    @pytest.mark.asyncio
    async def test_disconnect_one_of_multiple_keeps_others(self):
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect(ws1, user)
        await mgr.connect(ws2, user)
        await mgr.disconnect(ws1, user)
        assert len(mgr._connections["u1"]) == 1
        assert ws2 in mgr._connections["u1"]


class TestSendToUser:
    @pytest.mark.asyncio
    async def test_send_to_user_pushes_to_all_connections(self):
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect(ws1, user)
        await mgr.connect(ws2, user)
        await mgr.send_to_user("u1", {"type": "test"})
        ws1.send_json.assert_called_once_with({"type": "test"})
        ws2.send_json.assert_called_once_with({"type": "test"})

    @pytest.mark.asyncio
    async def test_send_to_unknown_user_is_noop(self):
        mgr = ConnectionManager()
        await mgr.send_to_user("nobody", {"type": "test"})  # 不应抛异常

    @pytest.mark.asyncio
    async def test_send_cleans_up_disconnected(self):
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws = _make_ws()
        ws.send_json.side_effect = Exception("disconnected")
        await mgr.connect(ws, user)
        await mgr.send_to_user("u1", {"type": "test"})
        # 异常连接应被清理
        assert "u1" not in mgr._connections


class TestEventBridge:
    def test_pushable_events_contains_task_events(self):
        assert EventType.TASK_PUBLISHED in WS_PUSHABLE_EVENTS
        assert EventType.TASK_COMPLETED in WS_PUSHABLE_EVENTS
        assert EventType.SUBTASK_COMPLETED in WS_PUSHABLE_EVENTS

    def test_extract_user_ids_from_task_event(self):
        event = Event(
            type=EventType.TASK_COMPLETED,
            payload={"task_id": "t1", "demander_id": "u_demander"},
        )
        ids = _extract_user_ids(event)
        assert "u_demander" in ids

    def test_extract_user_ids_unknown_payload_returns_empty(self):
        event = Event(type=EventType.TASK_COMPLETED, payload={})
        ids = _extract_user_ids(event)
        assert ids == []

    def test_format_ws_message_has_type_timestamp_data(self):
        event = Event(
            type=EventType.TASK_COMPLETED,
            payload={"task_id": "t1"},
            timestamp=1719600000.0,
        )
        msg = _format_ws_message(event)
        assert msg["type"] == "task.completed"
        assert "timestamp" in msg
        assert msg["data"]["task_id"] == "t1"

    def test_bridge_skips_non_pushable_events(self):
        mgr = MagicMock()
        mgr.send_to_user = AsyncMock()
        loop = asyncio.new_event_loop()
        try:
            bridge = make_ws_event_bridge(mgr, loop)
            # MATCH_PROPOSED 不在白名单
            event = Event(type=EventType.MATCH_PROPOSED, payload={"task_id": "t1"})
            bridge(event)
            # 不应调用 send_to_user
            mgr.send_to_user.assert_not_called()
        finally:
            loop.close()
