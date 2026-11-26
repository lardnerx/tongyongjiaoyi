"""陪驾教练 router 测试。

不依赖 orders router（任务16），直接在 fixture 中通过 server.deal_repo
预设一个 PENDING deal，避免并行执行依赖。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_deal():
    """带陪驾插件和预设 deal 的 FastAPI 应用。"""
    from umcp_core.core.deal import Deal
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
                supplier_id="supplier_1",
                domain_tag=DomainTag.of("escort"),
                resource_id="coach_1",
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "AUTO"

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach())
    # 预设一个 PENDING deal
    deal = Deal(
        task_id="task_1",
        resource_id="coach_1",
        demander_id="student_1",
        supplier_id="supplier_1",
        deal_id="deal_1",
    )
    server.deal_repo.save(deal)
    config = TransportConfig(jwt_secret="test-secret")
    return create_app(server, config)


@pytest.fixture
def client(app_with_deal):
    return TestClient(app_with_deal)


@pytest.fixture
def authed_client(client, jwt_service):
    from umcp_core.core.domain import Credential
    from umcp_core.layers.l1 import PhoneAuthProvider
    user = PhoneAuthProvider().authenticate(Credential("phone", "13800000000"))
    token = jwt_service.issue(user)["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_coach_accept_deal(authed_client):
    """教练接单：PENDING → ACTIVE。"""
    resp = authed_client.post(
        "/api/v1/escort/coaches/deals/deal_1/accept",
        json={"coach_id": "coach_1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


def test_coach_check_in(authed_client):
    """教练签到：ACTIVE → IN_SERVICE。"""
    # 先接单
    authed_client.post(
        "/api/v1/escort/coaches/deals/deal_1/accept",
        json={"coach_id": "coach_1"},
    )
    resp = authed_client.post(
        "/api/v1/escort/coaches/deals/deal_1/check-in",
        json={"coach_id": "coach_1", "lat": 39.9042, "lng": 116.4074},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "in_service"


def test_coach_check_out(authed_client):
    """教练签退：IN_SERVICE → COMPLETED。"""
    # 接单 + 签到
    authed_client.post(
        "/api/v1/escort/coaches/deals/deal_1/accept",
        json={"coach_id": "coach_1"},
    )
    authed_client.post(
        "/api/v1/escort/coaches/deals/deal_1/check-in",
        json={"coach_id": "coach_1", "lat": 39.9042, "lng": 116.4074},
    )
    resp = authed_client.post(
        "/api/v1/escort/coaches/deals/deal_1/check-out",
        json={"coach_id": "coach_1", "lat": 39.9050, "lng": 116.4080},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"


# ---------------------------------------------------------------------------
# Task / Deal 状态一致性：两个签到入口必须同步推进 Task 与 Deal
# ---------------------------------------------------------------------------


@pytest.fixture
def claimed_order(authed_client):
    """实时单：下单 → 抢单，返回 (client, task_id, deal_id, uid, server)。"""
    client = authed_client
    server = client.app.state.server
    uid = client.get("/api/v1/auth/me").json()["data"]["user_id"]

    created = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": uid,
            "domain_tag": "escort",
            "origin_lat": 39.9042,
            "origin_lng": 116.4074,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
    )
    task_id = created.json()["data"]["task_id"]
    claimed = client.post(
        f"/api/v1/escort/orders/{task_id}/claim", json={"coach_id": uid}
    )
    deal_id = claimed.json()["data"]["deal_id"]
    return client, task_id, deal_id, uid, server


def test_deal_check_in_advances_bound_task(claimed_order):
    """Deal 维度签到同时把绑定的 Task 推进到 in_progress。"""
    client, task_id, deal_id, uid, server = claimed_order

    resp = client.post(
        f"/api/v1/escort/coaches/deals/{deal_id}/check-in",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "in_service"

    task = server.task_repo.find_by_id(task_id)
    assert task.status == "in_progress"
    assert task.structured_fields.get("check_in_at")


def test_deal_check_out_advances_bound_task(claimed_order):
    """Deal 维度签退同时把绑定的 Task 推进到 completed。"""
    client, task_id, deal_id, uid, server = claimed_order

    client.post(
        f"/api/v1/escort/coaches/deals/{deal_id}/check-in",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )
    resp = client.post(
        f"/api/v1/escort/coaches/deals/{deal_id}/check-out",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"

    task = server.task_repo.find_by_id(task_id)
    assert task.status == "completed"
    assert task.structured_fields.get("check_out_at")


def test_orders_check_in_out_after_deal_entry_is_idempotent(claimed_order):
    """先走 Deal 入口再走订单入口：重复签到/签退保持幂等，状态不分叉。"""
    client, task_id, deal_id, uid, server = claimed_order

    client.post(
        f"/api/v1/escort/coaches/deals/{deal_id}/check-in",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )
    check_in = client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )
    assert check_in.status_code == 200
    assert check_in.json()["data"]["status"] == "in_progress"
    assert server.deal_repo.find_by_id(deal_id).status == "in_service"

    check_out = client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )
    assert check_out.status_code == 200
    assert check_out.json()["data"]["status"] == "completed"
    assert server.deal_repo.find_by_id(deal_id).status == "completed"

