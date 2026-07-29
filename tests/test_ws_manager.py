"""ConnectionManager 单元测试。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
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

    @pytest.mark.asyncio
    async def test_send_to_user_logs_exception(self, caplog):
        """send_to_user 推送失败应记录日志，不应静默吞掉。"""
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws = _make_ws()
        ws.send_json.side_effect = RuntimeError("connection broken")
        await mgr.connect(ws, user)
        with caplog.at_level(logging.DEBUG, logger="umcp_core.transport.ws"):
            await mgr.send_to_user("u1", {"type": "test"})
        assert any(
            r.exc_info and "connection broken" in str(r.exc_info[1])
            for r in caplog.records
        )


class TestConnectionManagerDisconnectAll:
    @pytest.mark.asyncio
    async def test_disconnect_all_closes_all_connections(self):
        mgr = ConnectionManager()
        user1 = _make_user("u1")
        user2 = _make_user("u2")
        ws1 = _make_ws()
        ws1.close = AsyncMock()
        ws2 = _make_ws()
        ws2.close = AsyncMock()
        await mgr.connect(ws1, user1)
        await mgr.connect(ws2, user2)
        await mgr.disconnect_all()
        assert mgr._connections == {}
        ws1.close.assert_called_once()
        ws2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_all_logs_exception(self, caplog):
        """disconnect_all 关闭失败应记录日志，不应静默吞掉。"""
        mgr = ConnectionManager()
        user = _make_user("u1")
        ws = _make_ws()
        ws.close = AsyncMock(side_effect=RuntimeError("close failed"))
        await mgr.connect(ws, user)
        with caplog.at_level(logging.DEBUG, logger="umcp_core.transport.ws"):
            await mgr.disconnect_all()
        assert mgr._connections == {}
        assert any(
            r.exc_info and "close failed" in str(r.exc_info[1])
            for r in caplog.records
        )


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

    def test_extract_user_ids_from_supplier_id(self):
        event = Event(
            type=EventType.RESOURCE_STATUS_CHANGED,
            payload={"resource_id": "r1", "supplier_id": "u_supplier"},
        )
        ids = _extract_user_ids(event)
        assert ids == ["u_supplier"]

    def test_extract_user_ids_from_user_id(self):
        event = Event(
            type=EventType.TRUST_UPDATED,
            payload={"user_id": "u_user"},
        )
        ids = _extract_user_ids(event)
        assert ids == ["u_user"]

    def test_extract_user_ids_dedup(self):
        """demander_id 和 supplier_id 值相同时应去重。"""
        event = Event(
            type=EventType.TASK_COMPLETED,
            payload={"demander_id": "u1", "supplier_id": "u1"},
        )
        ids = _extract_user_ids(event)
        assert ids == ["u1"]

    def test_extract_user_ids_payload_none(self):
        """payload=None 应返回空列表。"""
        event = Event(type=EventType.TASK_COMPLETED, payload=None)
        ids = _extract_user_ids(event)
        assert ids == []

    def test_extract_user_ids_filters_non_str_values(self):
        """非 str 值（None/int）应被过滤掉，不放入 ids。"""
        event = Event(
            type=EventType.TASK_COMPLETED,
            payload={"demander_id": None, "supplier_id": 123, "user_id": "u1"},
        )
        ids = _extract_user_ids(event)
        assert ids == ["u1"]

    def test_bridge_pushes_to_matching_users(self):
        mgr = MagicMock()
        mgr.send_to_user = AsyncMock()
        loop = asyncio.new_event_loop()

        def run_loop():
            loop.run_forever()

        t = threading.Thread(target=run_loop, daemon=True)
        t.start()
        try:
            bridge = make_ws_event_bridge(mgr, loop)
            event = Event(
                type=EventType.TASK_COMPLETED,
                payload={"task_id": "t1", "demander_id": "u1"},
            )
            bridge(event)
            time.sleep(0.2)  # 等待协程执行
            mgr.send_to_user.assert_called_once()
            call_args = mgr.send_to_user.call_args
            assert call_args[0][0] == "u1"  # 第一个位置参数是 user_id
            assert call_args[0][1]["type"] == "task.completed"  # 第二个位置参数是 message
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=1)
            loop.close()

    def test_bridge_logs_future_exception(self, caplog):
        """协程异常应被记录，不应静默吞掉。"""
        mgr = MagicMock()
        mgr.send_to_user = AsyncMock(side_effect=RuntimeError("push failed"))
        loop = asyncio.new_event_loop()

        def run_loop():
            loop.run_forever()

        t = threading.Thread(target=run_loop, daemon=True)
        t.start()
        try:
            bridge = make_ws_event_bridge(mgr, loop)
            event = Event(
                type=EventType.TASK_COMPLETED,
                payload={"task_id": "t1", "demander_id": "u1"},
            )
            with caplog.at_level(logging.WARNING, logger="umcp_core.transport.ws"):
                bridge(event)
                time.sleep(0.3)  # 等待协程执行和 done 回调
            assert any("WS 推送协程异常" in r.message for r in caplog.records)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=2)
            loop.close()
