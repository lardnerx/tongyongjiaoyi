"""预约单 select-coach 端点测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    """带陪驾插件 + 教练资源的 FastAPI 应用。"""
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    from plugins.escort_driving import register_plugin

    class _Coach(Resource):
        def __init__(self, rid, level="B"):
            super().__init__(
                supplier_id=rid,
                domain_tag=DomainTag.of("escort"),
                resource_id=rid,
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "manual"
            self.metadata["coach_level"] = level

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach("coach_1", "B"))
    server.resource_repo.save(_Coach("coach_2", "A"))
    server.resource_repo.save(_Coach("coach_3", "B"))
    config = TransportConfig(jwt_secret="test-secret")
    return TestClient(create_app(server, config)), server


def _auth_headers(server, user_id="u1", roles=None):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    if roles and "supplier" in roles:
        user.add_role(_ClaimsSupplier())
    if roles:
        user.switch_role(roles[0])
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_scheduled_order(client, server, demander_id="u1"):
    """创建预约单，返回 (task_id, candidates)。"""
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": demander_id,
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
            "coach_level_pref": "ANY",
        },
        headers=_auth_headers(server, demander_id),
    )
    data = resp.json()["data"]
    return data["task_id"], data["candidates"]


def test_select_coach_creates_deal(client_and_server):
    """学员选教练后创建 Deal(pending)，task 状态变为 assigned。"""
    client, server = client_and_server
    task_id, candidates = _create_scheduled_order(client, server)
    assert len(candidates) > 0

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deal_id"]
    assert data["status"] == "pending"
    assert data["deposit_amount"] > 0

    # task 状态应为 assigned
    task_resp = client.get(
        f"/api/v1/escort/orders/{task_id}",
        headers=_auth_headers(server),
    )
    assert task_resp.json()["data"]["status"] == "assigned"
    assert task_resp.json()["data"]["deal_id"] == data["deal_id"]


def test_select_coach_wrong_task_state_fails(client_and_server):
    """task 非 draft 状态时选教练失败（409）。"""
    client, server = client_and_server
    task_id, candidates = _create_scheduled_order(client, server)
    # 先选一次
    client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth_headers(server),
    )
    # 再选应失败（task 已 assigned）
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[1] if len(candidates) > 1 else candidates[0]},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 409


def test_select_non_candidate_fails(client_and_server):
    """选择不在候选列表中的教练失败（403）。"""
    client, server = client_and_server
    task_id, candidates = _create_scheduled_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": "non_existent_coach"},
        headers=_auth_headers(server),
    )
    assert resp.status_code in (403, 404)
