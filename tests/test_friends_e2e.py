"""好友社交端到端集成测试。

覆盖：
1. 发送好友请求
2. 接收方查看请求
3. 接受请求 → 双方成为好友
4. 好友列表
5. 删除好友
6. WS 事件发布验证
7. 非 receiving 方不能操作
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


@pytest.fixture(autouse=True)
def _clear_friends_store():
    """每个测试前后清空好友内存存储，避免测试间状态泄漏。"""
    from umcp_core.transport.routers.friends import _friend_requests_store, _friendships_store
    _friend_requests_store.clear()
    _friendships_store.clear()
    yield
    _friend_requests_store.clear()
    _friendships_store.clear()


def _user_headers(server, user_id: str = "student1", roles: list[str] | None = None):
    """生成普通用户 token 请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name=f"User-{user_id}")
    role_map = {"demander": _ClaimsDemander, "supplier": _ClaimsSupplier}
    for r in (roles or ["demander"]):
        if r in role_map:
            user.add_role(role_map[r]())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_e2e_full_friendship_flow(app_client):
    """完整好友流程：发送→查看→接受→列表→删除。"""
    client, server = app_client

    # 1. student1 向 coach1 发送好友请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1", "message": "服务很好"},
    )
    assert resp.status_code == 200
    request_id = resp.json()["data"]["request_id"]

    # 2. coach1 查看收到的好友请求
    resp2 = client.get(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "coach1"),
    )
    assert resp2.status_code == 200
    assert len(resp2.json()["data"]) >= 1

    # 3. coach1 接受请求
    resp3 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )
    assert resp3.status_code == 200
    assert resp3.json()["data"]["status"] == "accepted"

    # 4. 双方好友列表都应包含对方
    resp4 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert any(f["friend_user_id"] == "coach1" for f in resp4.json()["data"])

    resp5 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    assert any(f["friend_user_id"] == "student1" for f in resp5.json()["data"])

    # 5. student1 删除 coach1
    resp6 = client.delete(
        "/api/v1/friends/coach1",
        headers=_user_headers(server, "student1"),
    )
    assert resp6.status_code == 200

    # 双方好友列表都应为空
    resp7 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert len(resp7.json()["data"]) == 0

    resp8 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    assert len(resp8.json()["data"]) == 0


def test_e2e_reject_then_resend(app_client):
    """拒绝后可以重新发送请求。"""
    client, server = app_client

    # 第一次请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # coach1 拒绝
    client.post(
        f"/api/v1/friends/requests/{request_id}/reject",
        headers=_user_headers(server, "coach1"),
    )

    # 重新发送请求（应成功，因为旧请求已是 rejected 状态）
    resp2 = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    assert resp2.status_code == 200


def test_e2e_events_published(app_client):
    """验证好友事件被发布到 EventBus。"""
    client, server = app_client

    # 收集发布的事件
    events = []
    server.event_bus.subscribe_all(lambda e: events.append(e))

    # 发送请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # 接受请求
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    # 验证事件
    event_types = [e.type.value for e in events]
    assert "friend_request.created" in event_types
    assert "friend_request.accepted" in event_types


def test_e2e_non_recipient_cannot_accept(app_client):
    """非接收方不能接受请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # student2 尝试接受
    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "student2"),
    )
    assert resp2.status_code == 403
