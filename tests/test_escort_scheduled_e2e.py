"""预约单全流程集成测试：下单→选教练→支付→确认→签到→签退→评价。"""
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
        def __init__(self, rid="coach_1"):
            super().__init__(
                supplier_id=rid,
                domain_tag=DomainTag.of("escort"),
                resource_id=rid,
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
    server.resource_repo.save(_Coach("coach_1"))
    config = TransportConfig(jwt_secret="test-secret")
    return TestClient(create_app(server, config)), server


def _auth(server, user_id="u1", roles=None):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    if roles and "supplier" in roles:
        user.add_role(_ClaimsSupplier())
    if roles:
        user.switch_role(roles[0])
    return {"Authorization": f"Bearer {jwt.issue(user)['access_token']}"}


def test_scheduled_full_flow(client_and_server):
    """预约单全流程：下单→选教练→支付→确认→签到→签退→双向评价。"""
    client, server = client_and_server

    # 1. 学员创建预约单
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1", "domain_tag": "escort",
            "origin_lat": 39.9, "origin_lng": 116.4,
            "car_type": "manual", "required_skills": [],
            "duration_hours": 2, "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=_auth(server),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]
    candidates = resp.json()["data"]["candidates"]
    assert len(candidates) > 0

    # 2. 学员选教练
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth(server),
    )
    assert resp.status_code == 200
    deal_id = resp.json()["data"]["deal_id"]
    deposit = resp.json()["data"]["deposit_amount"]
    assert deposit > 0

    # 3. 学员 Mock 支付定金
    resp = client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth(server),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "paid"

    # 4. 教练确认
    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": candidates[0]},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"

    # 5. 教练签到（复用 task-based check-in）
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": candidates[0], "lat": 39.9, "lng": 116.4},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "in_progress"

    # 6. 教练签退
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": candidates[0], "lat": 39.9, "lng": 116.4},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"

    # 7. 学员评教练
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "很好",
        },
        headers=_auth(server),
    )
    assert resp.status_code == 200

    # 8. 教练评学员
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": candidates[0],
            "reviewer_role": "COACH",
            "ratings": {"punctuality_score": 5, "cooperation_score": 4, "payment_score": 5},
            "comment": "不错",
        },
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200

    # 9. 验证评价记录
    resp = client.get(
        f"/api/v1/escort/orders/{task_id}/reviews",
        headers=_auth(server),
    )
    assert resp.status_code == 200
    reviews = resp.json()["data"]
    assert len(reviews) == 2


def test_scheduled_reject_flow(client_and_server):
    """教练拒绝预约单：deal cancelled + task cancelled。"""
    client, server = client_and_server

    # 下单 → 选教练 → 支付
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1", "domain_tag": "escort",
            "origin_lat": 39.9, "origin_lng": 116.4,
            "car_type": "manual", "required_skills": [],
            "duration_hours": 2, "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=_auth(server),
    )
    task_id = resp.json()["data"]["task_id"]
    candidates = resp.json()["data"]["candidates"]

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth(server),
    )
    deal_id = resp.json()["data"]["deal_id"]

    client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth(server),
    )

    # 教练拒绝
    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/reject",
        json={"coach_id": candidates[0], "reason": "时间冲突"},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"

    # task 也应被取消
    resp = client.get(
        f"/api/v1/escort/orders/{task_id}",
        headers=_auth(server),
    )
    assert resp.json()["data"]["status"] == "cancelled"
