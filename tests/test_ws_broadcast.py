"""ConnectionManager 广播能力测试。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from umcp_core.transport.ws import ConnectionManager


@pytest.mark.asyncio
async def test_register_and_unregister_online_coach():
    """教练上线注册、下线移除。"""
    mgr = ConnectionManager()
    mgr.register_online_coach("coach_1")
    mgr.register_online_coach("coach_2")
    assert mgr.online_coaches == {"coach_1", "coach_2"}
    mgr.unregister_online_coach("coach_1")
    assert mgr.online_coaches == {"coach_2"}


@pytest.mark.asyncio
async def test_broadcast_to_online_coaches_sends_to_all():
    """广播消息发送给所有在线教练。"""
    mgr = ConnectionManager()
    mgr.register_online_coach("coach_1")
    mgr.register_online_coach("coach_2")

    mgr.send_to_user = AsyncMock()
    message = {"type": "task.published", "data": {}}

    await mgr.broadcast_to_online_coaches(message)

    assert mgr.send_to_user.await_count == 2
    called_ids = {call.args[0] for call in mgr.send_to_user.await_args_list}
    assert called_ids == {"coach_1", "coach_2"}


@pytest.mark.asyncio
async def test_broadcast_to_online_coaches_empty_set():
    """无在线教练时不发送。"""
    mgr = ConnectionManager()
    mgr.send_to_user = AsyncMock()
    await mgr.broadcast_to_online_coaches({"type": "test"})
    assert mgr.send_to_user.await_count == 0
