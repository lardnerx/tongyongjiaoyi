"""教练上线/下线接口测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    """带陪驾插件的 FastAPI 应用。"""
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsSupplier
    from plugins.escort_driving import register_plugin

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    client = TestClient(app)
    return client, server


def _auth_headers(server, user_id="coach_1"):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsSupplier
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Coach")
    user.add_role(_ClaimsSupplier())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_coach_online_registers(client_and_server):
    """教练上线后注册到在线集合。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/escort/coaches/coach_1/online",
        json={"lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    assert "coach_1" in server.ws_manager.online_suppliers


def test_coach_offline_removes(client_and_server):
    """教练下线后从在线集合移除。"""
    client, server = client_and_server
    client.post(
        "/api/v1/escort/coaches/coach_1/online",
        json={"lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server),
    )
    resp = client.post(
        "/api/v1/escort/coaches/coach_1/offline",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    assert "coach_1" not in server.ws_manager.online_suppliers
