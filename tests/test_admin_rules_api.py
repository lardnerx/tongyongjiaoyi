"""验证 admin/rules 端点（list/detail/update/history/rollback）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsAdmin, _ClaimsDemander


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _admin_headers(server, user_id="admin1"):
    """生成 admin token 请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Admin")
    user.add_role(_ClaimsAdmin())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _user_headers(server, user_id="student1"):
    """生成普通用户 token 请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Student")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_list_rules_requires_admin(app_client):
    """非 admin 用户访问 /admin/rules 应返回 403。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_user_headers(server))
    assert resp.status_code == 403


def test_list_rules_returns_all(app_client):
    """admin 用户应获取所有规则（含默认值）。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_admin_headers(server))
    assert resp.status_code == 200
    rules = resp.json()["data"]
    keys = [r["rule_key"] for r in rules]
    assert "escort.cancel.realtime.timeout_seconds" in keys
    assert "escort.cancel.realtime.expand_after_seconds" in keys
    assert "escort.cancel.scheduled.penalty_tiers" in keys


def test_list_rules_filter_by_category(app_client):
    """按 category 过滤规则。"""
    client, server = app_client
    resp = client.get(
        "/api/v1/admin/rules?category=escort.cancel",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    rules = resp.json()["data"]
    for r in rules:
        assert r["category"] == "escort.cancel"


def test_get_rule_detail(app_client):
    """查询单个规则详情。"""
    client, server = app_client
    resp = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["rule_key"] == "escort.cancel.realtime.timeout_seconds"
    assert data["rule_value"] == 60


def test_get_rule_detail_not_found(app_client):
    """查询不存在的规则返回 404。"""
    client, server = app_client
    resp = client.get(
        "/api/v1/admin/rules/nonexistent.key",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 404


def test_update_rule_changes_value(app_client):
    """admin 更新规则值后应反映在新值中。"""
    client, server = app_client
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 120, "reason": "延长超时时间"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["rule_value"] == 120
    assert data["version"] >= 1

    # 验证 get 也返回新值
    resp2 = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
    )
    assert resp2.json()["data"]["rule_value"] == 120


def test_update_rule_records_history(app_client):
    """更新规则应产生历史记录。"""
    client, server = app_client
    client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 90, "reason": "测试历史"},
    )
    resp = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds/history",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    history = resp.json()["data"]
    assert len(history) >= 1
    assert history[-1]["new_value"] == 90
    assert history[-1]["change_reason"] == "测试历史"


def test_update_rule_requires_reason(app_client):
    """更新规则时 reason 不可为空。"""
    client, server = app_client
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 120, "reason": ""},
    )
    assert resp.status_code == 422
