"""验证 /api/v1/escort/cancel-rules 端点返回取消规则。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _auth_headers(server, user_id="student1"):
    """生成已认证请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_get_cancel_rules(app_client):
    """应返回默认取消规则。"""
    client, server = app_client
    resp = client.get(
        "/api/v1/escort/cancel-rules",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["timeout_seconds"] == 60
    assert data["expand_after_seconds"] == 30
    assert data["penalty_tiers"] == [
        {"hours_before": 24, "penalty": 0.2},
        {"hours_before": 12, "penalty": 0.5},
        {"hours_before": 4, "penalty": 1.0},
        {"hours_before": 0, "penalty": 2.0},
    ]


def test_get_cancel_rules_reflects_overrides(app_client):
    """运营覆盖规则后端点应返回新值。"""
    client, server = app_client
    server.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=120,
        updated_by="admin",
        category="escort.cancel",
    )
    resp = client.get(
        "/api/v1/escort/cancel-rules",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["timeout_seconds"] == 120
