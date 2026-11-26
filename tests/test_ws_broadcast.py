"""ConnectionManager 广播能力测试。"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from umcp_core.transport.ws import ConnectionManager


@pytest.mark.asyncio
async def test_register_and_unregister_online_supplier():
    """供给方上线注册、下线移除。"""
    mgr = ConnectionManager()
    mgr.register_online_supplier("coach_1")
    mgr.register_online_supplier("coach_2")
    assert mgr.online_suppliers == {"coach_1", "coach_2"}
    mgr.unregister_online_supplier("coach_1")
    assert mgr.online_suppliers == {"coach_2"}


@pytest.mark.asyncio
async def test_broadcast_to_online_suppliers_sends_to_all():
    """广播消息发送给所有在线供给方。"""
    mgr = ConnectionManager()
    mgr.register_online_supplier("coach_1")
    mgr.register_online_supplier("coach_2")

    mgr.send_to_user = AsyncMock()
    message = {"type": "task.published", "data": {}}

    await mgr.broadcast_to_online_suppliers(message)

    assert mgr.send_to_user.await_count == 2
    called_ids = {call.args[0] for call in mgr.send_to_user.await_args_list}
    assert called_ids == {"coach_1", "coach_2"}


@pytest.mark.asyncio
async def test_broadcast_to_online_suppliers_empty_set():
    """无在线供给方时不发送。"""
    mgr = ConnectionManager()
    mgr.send_to_user = AsyncMock()
    await mgr.broadcast_to_online_suppliers({"type": "test"})
    assert mgr.send_to_user.await_count == 0
