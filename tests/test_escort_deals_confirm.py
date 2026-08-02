"""教练确认/拒绝预约单端点测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from plugins.escort_driving import register_plugin

    class _Coach(Resource):
        def __init__(self):
            super().__init__(
                supplier_id="coach_1",
                domain_tag=DomainTag.of("escort"),
                resource_id="coach_1",
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "manual"
            self.metadata["coach_level"] = "B"

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach())
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


def _setup_paid_deal(client, server):
    """创建预约单→选教练→Mock支付，返回 (task_id, deal_id)。"""
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9, "origin_lng": 116.4,
            "car_type": "manual", "required_skills": [],
            "duration_hours": 2, "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=_auth_headers(server),
    )
    task_id = resp.json()["data"]["task_id"]
    candidates = resp.json()["data"]["candidates"]
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth_headers(server),
    )
    deal_id = resp2.json()["data"]["deal_id"]
    client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    return task_id, deal_id


def test_coach_confirm_deal(client_and_server):
    """教练确认预约单：deal pending → active。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)

    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


def test_coach_reject_deal(client_and_server):
    """教练拒绝预约单：deal pending → cancelled + 退款。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)

    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/reject",
        json={"coach_id": "coach_1", "reason": "时间冲突"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


def test_confirm_wrong_coach_fails(client_and_server):
    """非该订单教练确认失败（403）。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)

    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_other"},
        headers=_auth_headers(server, "coach_other", roles=["supplier"]),
    )
    assert resp.status_code == 403


def test_confirm_already_active_fails(client_and_server):
    """已确认的 deal 再次确认失败（409）。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)
    client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 409
