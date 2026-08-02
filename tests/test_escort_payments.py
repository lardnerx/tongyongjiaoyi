"""Mock 支付端点测试。"""
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


def _auth_headers(server, user_id="u1"):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _setup_scheduled_deal(client, server):
    """创建预约单 + 选教练，返回 (task_id, deal_id, deposit_amount)。"""
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": [],
            "duration_hours": 2,
            "order_type": "SCHEDULED",
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
    data = resp2.json()["data"]
    return task_id, data["deal_id"], data["deposit_amount"]


def test_mock_pay_success(client_and_server):
    """Mock 支付定金成功，支付状态变为 paid。"""
    client, server = client_and_server
    task_id, deal_id, deposit = _setup_scheduled_deal(client, server)

    resp = client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "paid"
    assert data["amount"] == deposit
    assert data["payment_id"]


def test_query_payment_by_deal(client_and_server):
    """按 deal_id 查询支付状态。"""
    client, server = client_and_server
    task_id, deal_id, _ = _setup_scheduled_deal(client, server)
    client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    resp = client.get(
        f"/api/v1/escort/payments/{deal_id}",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "paid"
    assert data["deal_id"] == deal_id


def test_mock_pay_nonexistent_deal_fails(client_and_server):
    """支付不存在的 deal 返回 404。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": "nonexistent", "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 404
