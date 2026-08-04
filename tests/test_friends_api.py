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
