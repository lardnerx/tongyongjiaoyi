"""角色切换接口测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.transport.auth import JwtService


@pytest.fixture
def client_and_server():
    """带认证的 FastAPI 应用。"""
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from umcp_core.transport.auth import _ClaimsUser, _ClaimsDemander, _ClaimsSupplier

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    client = TestClient(app)
    return client, server


def _auth_headers(server, user_id="u1", active_role="demander"):
    """生成已认证请求头（用户同时拥有 demander 和 supplier 角色）。"""
    from umcp_core.transport.auth import _ClaimsUser, _ClaimsDemander, _ClaimsSupplier

    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    user.add_role(_ClaimsSupplier())
    user.switch_role(active_role)
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_switch_role_success(client_and_server):
    """切换角色成功，返回新 token。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/auth/switch-role",
        json={"role": "supplier"},
        headers=_auth_headers(server, "u1", "demander"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    # 新 token 的 active_role 应为 supplier
    new_token = data["access_token"]
    decoded = JwtService("test-secret").decode(new_token)
    assert decoded["active_role"] == "supplier"


def test_switch_role_invalid_fails(client_and_server):
    """切换到未关联角色失败（409，因为用户已认证，是状态非法而非凭据无效）。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/auth/switch-role",
        json={"role": "admin"},
        headers=_auth_headers(server, "u1", "demander"),
    )
    assert resp.status_code == 409
