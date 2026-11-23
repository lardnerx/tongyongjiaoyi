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


def test_confirm_payment_after_completed(authed_client):
    """客户在已完成订单上确认完成并支付，记录确认时间与结算金额。"""
    uid = authed_client.get("/api/v1/auth/me").json()["data"]["user_id"]
    create_resp = authed_client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": uid,
            "domain_tag": "escort",
            "origin_lat": 39.9042,
            "origin_lng": 116.4074,
            "car_type": "economy",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
    )
    task_id = create_resp.json()["data"]["task_id"]

    # 未完成订单不允许确认支付
    early = authed_client.post(f"/api/v1/escort/orders/{task_id}/confirm")
    assert early.status_code >= 400

    authed_client.post(
        f"/api/v1/escort/orders/{task_id}/claim", json={"coach_id": uid}
    )
    authed_client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )
    authed_client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    )

    confirmed = authed_client.post(f"/api/v1/escort/orders/{task_id}/confirm")
    data = confirmed.json()["data"]
    assert data["customer_confirmed_at"]
    assert data["settled_amount"] == 200.0

    # 重复确认幂等
    again = authed_client.post(f"/api/v1/escort/orders/{task_id}/confirm")
    assert again.status_code == 200
    assert again.json()["data"]["customer_confirmed_at"] == data["customer_confirmed_at"]

    # 司机余额 = 已确认支付订单金额合计
    balance = authed_client.get("/api/v1/escort/orders/balance").json()["data"]
    assert balance["balance"] == 200.0
    assert balance["order_count"] == 1


def test_check_in_out_records_timestamps(authed_client):
    """签到/签退记录时间戳，供计时页与结算页使用。"""
    uid = authed_client.get("/api/v1/auth/me").json()["data"]["user_id"]
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
    authed_client.post(
        f"/api/v1/escort/orders/{task_id}/claim", json={"coach_id": uid}
    )

    check_in = authed_client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    ).json()["data"]
    assert check_in["status"] == "in_progress"
    assert check_in["check_in_at"]

    check_out = authed_client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": uid, "lat": 39.9, "lng": 116.4},
    ).json()["data"]
    assert check_out["status"] == "completed"
    assert check_out["check_in_at"] == check_in["check_in_at"]
    assert check_out["check_out_at"]


def test_list_orders_by_coach_id(authed_client):
    """司机按 coach_id 能查到已接订单，其他司机查不到。"""
    uid = authed_client.get("/api/v1/auth/me").json()["data"]["user_id"]
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
    claim_resp = authed_client.post(
        f"/api/v1/escort/orders/{task_id}/claim", json={"coach_id": uid}
    )
    assert claim_resp.status_code == 200

    mine = authed_client.get("/api/v1/escort/orders", params={"coach_id": uid})
    assert task_id in [o["task_id"] for o in mine.json()["data"]]

    other = authed_client.get(
        "/api/v1/escort/orders", params={"coach_id": "coach_x"}
    )
    assert task_id not in [o["task_id"] for o in other.json()["data"]]


def test_list_orders_sorted_by_created_at_desc(authed_client):
    """我的订单按下单时间倒序返回（新单在前）。"""
    payload = {
        "demander_id": "student_1",
        "domain_tag": "escort",
        "origin_lat": 39.9042,
        "origin_lng": 116.4074,
        "car_type": "AUTO",
        "required_skills": ["escort"],
        "duration_hours": 2,
        "order_type": "REALTIME",
    }
    first_id = authed_client.post("/api/v1/escort/orders", json=payload).json()["data"]["task_id"]
    second_id = authed_client.post("/api/v1/escort/orders", json=payload).json()["data"]["task_id"]

    resp = authed_client.get(
        "/api/v1/escort/orders", params={"demander_id": "student_1"}
    )
    assert resp.status_code == 200
    ids = [o["task_id"] for o in resp.json()["data"]]
    assert ids[:2] == [second_id, first_id]


def test_list_available_orders(authed_client):
    """司机接单大厅可拉取待抢的实时单（含起点坐标）。"""
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

    resp = authed_client.get("/api/v1/escort/orders/available")
    assert resp.status_code == 200
    items = resp.json()["data"]
    target = next(o for o in items if o["task_id"] == task_id)
    assert target["status"] == "published"
    assert target["origin_lat"] == 39.9042
    assert target["origin_lng"] == 116.4074


def test_pick_coaches_for_order_filters_by_radius():
    """实时单首轮只推半径内在线教练；半径 <=0 时退化为全量在线教练。"""
    from types import SimpleNamespace

    from umcp_core.shared.lbs.in_memory import InMemoryLBSService
    from umcp_core.transport.routers.escort.orders import _pick_coaches_for_order

    lbs = InMemoryLBSService()
    lbs.update_location("near", 39.9042, 116.4074)
    lbs.update_location("far", 31.2304, 121.4737)
    server = SimpleNamespace(
        ws_manager=SimpleNamespace(online_coaches={"near", "far", "no_location"}),
        lbs_service=lbs,
    )

    # 5km 内只剩一个在线教练；无位置信息的教练不再收到首轮推送
    assert _pick_coaches_for_order(server, 39.9042, 116.4074, 5.0) == ["near"]

    # 半径为 0 表示不限距离
    assert set(_pick_coaches_for_order(server, 39.9042, 116.4074, 0)) == {
        "near",
        "far",
        "no_location",
    }

    # 未启用 LBS 时同样退化为全量
    server_no_lbs = SimpleNamespace(
        ws_manager=SimpleNamespace(online_coaches={"near"}), lbs_service=None
    )
    assert _pick_coaches_for_order(server_no_lbs, 39.9, 116.4, 5.0) == ["near"]

    # 半径内没有在线教练时退化为全部在线教练（无位置信息的司机也能收到）
    server_no_nearby = SimpleNamespace(
        ws_manager=SimpleNamespace(online_coaches={"no_location"}),
        lbs_service=lbs,
    )
    assert _pick_coaches_for_order(server_no_nearby, 39.9042, 116.4074, 1.0) == [
        "no_location"
    ]
