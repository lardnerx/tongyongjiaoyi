"""陪驾订单 router 测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_escort():
    """带陪驾插件的 FastAPI 应用。"""
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.layers.l3 import InstantMatch, MatchResult
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from plugins.escort_driving import register_plugin

    class _Coach(Resource):
        def __init__(self, rid="coach_1"):
            super().__init__(
                supplier_id="supplier_1",
                domain_tag=DomainTag.of("escort"),
                resource_id=rid,
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "AUTO"
            self.metadata["coach_level"] = "BRONZE"

        def resource_type(self) -> str:
            return "coach"

    class _RealtimeMatch(InstantMatch):
        def execute(self, task, candidates):
            return MatchResult(
                task_id=task.task_id,
                selected_resource_id="coach_1",
                candidates=[r.resource_id for r in candidates],
            )

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    # 覆盖实时单匹配策略：测试用 Coach 无 coach_license 资质，
    # 默认 InstantMatch + CredentialFilter 会过滤掉所有教练导致任务被取消。
    # 注册 _RealtimeMatch 让实时单能命中 coach_1，便于取消测试。
    server.register_match_strategy("escort", _RealtimeMatch())
    server.resource_repo.save(_Coach("coach_1"))
    server.resource_repo.save(_Coach("coach_2"))
    server.resource_repo.save(_Coach("coach_3"))
    config = TransportConfig(jwt_secret="test-secret")
    return create_app(server, config)


@pytest.fixture
def client(app_with_escort):
    return TestClient(app_with_escort)


@pytest.fixture
def authed_client(client, jwt_service):
    """预登录的 TestClient。"""
    from umcp_core.core.domain import Credential
    from umcp_core.layers.l1 import PhoneAuthProvider
    user = PhoneAuthProvider().authenticate(Credential("phone", "13800000000"))
    token = jwt_service.issue(user)["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_create_realtime_order(authed_client):
    """学员创建实时单。"""
    resp = authed_client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "student_1",
            "domain_tag": "escort",
            "origin_lat": 39.9042,
            "origin_lng": 116.4074,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
            "title": "下班回家",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert data["data"]["order_type"] == "REALTIME"
    assert data["data"]["task_id"]


def test_create_scheduled_order_returns_candidates(authed_client):
    """学员创建预约单，返回 Top3 候选教练。"""
    resp = authed_client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "student_1",
            "domain_tag": "escort",
            "origin_lat": 39.9042,
            "origin_lng": 116.4074,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-15T10:00:00",
            "coach_level_pref": "BRONZE",
            "title": "周末练车",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["order_type"] == "SCHEDULED"
    assert data["task_id"]
    assert isinstance(data["candidates"], list)
    assert len(data["candidates"]) <= 3


def test_list_orders(authed_client):
    """查询学员订单列表。"""
    # 先创建一个订单
    authed_client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "student_1",
            "domain_tag": "escort",
            "origin_lat": 39.9042,
            "origin_lng": 116.4074,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
    )
    resp = authed_client.get("/api/v1/escort/orders?demander_id=student_1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)
    assert len(data) >= 1


def test_get_order_detail(authed_client):
    """查询单个订单详情。"""
    create_resp = authed_client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "student_1",
            "domain_tag": "escort",
            "origin_lat": 39.9042,
            "origin_lng": 116.4074,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
    )
    task_id = create_resp.json()["data"]["task_id"]
    resp = authed_client.get(f"/api/v1/escort/orders/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["task_id"] == task_id
    # created_at 必须带时区，否则前端按本地时区解析会早 8 小时并误判「已超时」
    created_at = resp.json()["data"]["created_at"]
    assert created_at is not None
    assert created_at.endswith("+00:00") or created_at.endswith("Z")


def test_cancel_order(authed_client, jwt_service):
    """学员取消订单。"""
    # 权限校验要求 demander_id 与登录用户一致，从 JWT 解析 user_id
    token = authed_client.headers["Authorization"].replace("Bearer ", "")
    user_id = jwt_service.decode(token)["sub"]
    create_resp = authed_client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": user_id,
            "domain_tag": "escort",
            "origin_lat": 39.9042,
            "origin_lng": 116.4074,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
    )
    task_id = create_resp.json()["data"]["task_id"]
    resp = authed_client.post(f"/api/v1/escort/orders/{task_id}/cancel")
    assert resp.status_code == 200
