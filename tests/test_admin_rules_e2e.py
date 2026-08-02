"""管理员规则配置端到端集成测试。

覆盖：
1. admin 查看规则列表
2. admin 更新规则 → 验证新值生效
3. admin 查看历史
4. admin 回滚规则
5. 非 admin 被拒绝
6. 更新后的规则值影响业务逻辑（cancel-rules 端点返回新值）
"""
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
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Admin")
    user.add_role(_ClaimsAdmin())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _user_headers(server, user_id="student1"):
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Student")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_e2e_admin_lists_rules(app_client):
    """admin 查看规则列表。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_admin_headers(server))
    assert resp.status_code == 200
    rules = resp.json()["data"]
    assert len(rules) >= 3


def test_e2e_non_admin_rejected(app_client):
    """非 admin 被拒绝访问。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_user_headers(server))
    assert resp.status_code == 403


def test_e2e_update_then_cancel_rules_reflects_change(app_client):
    """admin 更新规则后，/cancel-rules 端点应返回新值。"""
    client, server = app_client
    # 更新 timeout_seconds 为 120
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 120, "reason": "E2E 测试调整"},
    )
    assert resp.status_code == 200

    # /cancel-rules 应返回 120
    resp2 = client.get(
        "/api/v1/escort/cancel-rules",
        headers=_user_headers(server),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["timeout_seconds"] == 120


def test_e2e_update_history_rollback(app_client):
    """更新 → 历史 → 回滚完整流程。"""
    client, server = app_client
    rule_key = "escort.cancel.realtime.expand_after_seconds"

    # 初始值 30，改为 45
    client.put(
        f"/api/v1/admin/rules/{rule_key}",
        headers=_admin_headers(server),
        json={"value": 45, "reason": "第一次调整"},
    )
    # 再改为 60
    client.put(
        f"/api/v1/admin/rules/{rule_key}",
        headers=_admin_headers(server),
        json={"value": 60, "reason": "第二次调整"},
    )

    # 查看历史
    resp = client.get(
        f"/api/v1/admin/rules/{rule_key}/history",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    history = resp.json()["data"]
    assert len(history) >= 2

    # 找到 old_value 非 None 的记录回滚
    rollback_target = next(h for h in history if h["old_value"] is not None)
    old_val = rollback_target["old_value"]

    resp = client.post(
        f"/api/v1/admin/rules/{rule_key}/rollback",
        headers=_admin_headers(server),
        json={"history_id": rollback_target["history_id"], "reason": "E2E 回滚"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["rule_value"] == old_val


def test_e2e_update_penalty_tiers(app_client):
    """admin 更新罚分梯度（list 类型值）。"""
    client, server = app_client
    new_tiers = [
        {"hours_before": 48, "penalty": 0.1},
        {"hours_before": 0, "penalty": 3.0},
    ]
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.scheduled.penalty_tiers",
        headers=_admin_headers(server),
        json={"value": new_tiers, "reason": "调整罚分梯度"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["rule_value"] == new_tiers

    # /cancel-rules 应返回新梯度
    resp2 = client.get(
        "/api/v1/escort/cancel-rules",
        headers=_user_headers(server),
    )
    assert resp2.json()["data"]["penalty_tiers"] == new_tiers
