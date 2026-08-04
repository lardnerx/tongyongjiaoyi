"""验证 friends 端点（发送/接受/拒绝请求、好友列表、删除好友）。"""
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
    role_map = {
        "demander": _ClaimsDemander,
        "supplier": _ClaimsSupplier,
    }
    for r in (roles or ["demander"]):
        if r in role_map:
            user.add_role(role_map[r]())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_send_friend_request(app_client):
    """发送好友请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1", "message": "服务很好，加个好友"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["from_user_id"] == "student1"
    assert data["to_user_id"] == "coach1"
    assert data["status"] == "pending"
    assert data["request_id"].startswith("freq_")


def test_send_friend_request_to_self_rejected(app_client):
    """不能给自己发送好友请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "student1"},
    )
    assert resp.status_code == 409


def test_list_received_requests(app_client):
    """查看收到的好友请求。"""
    client, server = app_client
    # student1 向 coach1 发送请求
    client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    # coach1 查看收到的请求
    resp = client.get(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "coach1"),
    )
    assert resp.status_code == 200
    requests = resp.json()["data"]
    assert len(requests) >= 1
    assert requests[0]["to_user_id"] == "coach1"
    assert requests[0]["from_user_id"] == "student1"
    assert requests[0]["status"] == "pending"


def test_accept_friend_request(app_client):
    """接受好友请求后双方成为好友。"""
    client, server = app_client
    # student1 向 coach1 发送请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # coach1 接受请求
    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "accepted"

    # 双方都应在好友列表中
    resp3 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert resp3.status_code == 200
    friends = resp3.json()["data"]
    assert any(f["friend_user_id"] == "coach1" for f in friends)

    resp4 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    friends2 = resp4.json()["data"]
    assert any(f["friend_user_id"] == "student1" for f in friends2)


def test_accept_request_not_recipient(app_client):
    """非接收方不能接受请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # student2 尝试接受（非接收方）
    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "student2"),
    )
    assert resp2.status_code == 403


def test_reject_friend_request(app_client):
    """拒绝好友请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/reject",
        headers=_user_headers(server, "coach1"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "rejected"

    # 不应出现在好友列表中
    resp3 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    friends = resp3.json()["data"]
    assert not any(f["friend_user_id"] == "coach1" for f in friends)


def test_list_friends(app_client):
    """查看好友列表。"""
    client, server = app_client
    # 建立好友关系
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    resp2 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert resp2.status_code == 200
    friends = resp2.json()["data"]
    assert len(friends) == 1
    assert friends[0]["friend_user_id"] == "coach1"


def test_remove_friend(app_client):
    """删除好友（双向删除）。"""
    client, server = app_client
    # 建立好友关系
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    # student1 删除 coach1
    resp2 = client.delete(
        "/api/v1/friends/coach1",
        headers=_user_headers(server, "student1"),
    )
    assert resp2.status_code == 200

    # 双方好友列表都应为空
    resp3 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert len(resp3.json()["data"]) == 0

    resp4 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    assert len(resp4.json()["data"]) == 0


def test_duplicate_request_after_accept(app_client):
    """已是好友后再次发请求应被拒绝。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    # 再次发请求
    resp2 = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    assert resp2.status_code == 409


def test_accept_nonexistent_request(app_client):
    """接受不存在的好友请求返回 404。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests/nonexistent_id/accept",
        headers=_user_headers(server, "coach1"),
    )
    assert resp.status_code == 404
