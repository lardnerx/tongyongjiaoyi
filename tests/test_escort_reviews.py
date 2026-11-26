"""评价接口测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    """带陪驾插件的 FastAPI 应用。"""
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.layers.l3 import InstantMatch, MatchResult
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
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

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach("coach_1"))
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    client = TestClient(app)
    return client, server


def _auth_headers(server, user_id="u1", roles=None):
    """生成已认证请求头。"""
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


def _create_completed_order(client, server, demander_id="u1", coach_id="coach_1"):
    """创建一个已完成的订单（helper）。"""
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": demander_id,
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, demander_id),
    )
    task_id = resp.json()["data"]["task_id"]
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": coach_id},
        headers=_auth_headers(server, coach_id, roles=["supplier"]),
    )
    client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": coach_id, "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, coach_id, roles=["supplier"]),
    )
    client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": coach_id, "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, coach_id, roles=["supplier"]),
    )
    return task_id


def test_student_review_coach_success(client_and_server):
    """学员评价教练成功。"""
    client, server = client_and_server
    task_id = _create_completed_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "教练很专业",
        },
        headers=_auth_headers(server, "u1"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["evaluatee_id"] == "coach_1"
    assert data["reviewer_role"] == "STUDENT"


def test_coach_review_student_success(client_and_server):
    """教练评价学员成功。"""
    client, server = client_and_server
    task_id = _create_completed_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "coach_1",
            "reviewer_role": "COACH",
            "ratings": {"punctuality_score": 5, "cooperation_score": 4, "payment_score": 5},
            "comment": "学员很守时",
        },
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["evaluatee_id"] == "u1"
    assert data["reviewer_role"] == "COACH"


def test_duplicate_review_fails(client_and_server):
    """重复评价失败。"""
    client, server = client_and_server
    task_id = _create_completed_order(client, server)
    review_body = {
        "reviewer_id": "u1",
        "reviewer_role": "STUDENT",
        "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
        "comment": "好评",
    }
    client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json=review_body,
        headers=_auth_headers(server, "u1"),
    )
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json=review_body,
        headers=_auth_headers(server, "u1"),
    )
    assert resp2.status_code == 409


def test_review_not_completed_fails(client_and_server):
    """未完成订单不能评价。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "AUTO",
            "required_skills": ["escort"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, "u1"),
    )
    task_id = resp.json()["data"]["task_id"]
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "好评",
        },
        headers=_auth_headers(server, "u1"),
    )
    assert resp2.status_code == 409


def test_get_reviews(client_and_server):
    """查询订单评价。"""
    client, server = client_and_server
    task_id = _create_completed_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "好评",
        },
        headers=_auth_headers(server, "u1"),
    )
    resp = client.get(
        f"/api/v1/escort/orders/{task_id}/reviews",
        headers=_auth_headers(server, "u1"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["reviewer_role"] == "STUDENT"


def test_review_impersonation_fails(client_and_server):
    """用户不能替他人提交评价。"""
    client, server = client_and_server
    task_id = _create_completed_order(client, server, demander_id="u1")
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u_other",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5},
            "comment": "",
        },
        headers=_auth_headers(server, "u1"),  # 当前用户是 u1，但 reviewer_id 是 u_other
    )
    assert resp.status_code == 403


def test_non_participant_review_fails(client_and_server):
    """非订单参与方不能评价。"""
    client, server = client_and_server
    task_id = _create_completed_order(client, server, demander_id="u1")
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u_outsider",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5},
            "comment": "",
        },
        headers=_auth_headers(server, "u_outsider"),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 持久化：评价必须落 Repository，而不是模块级内存字典
# ---------------------------------------------------------------------------


def test_review_is_persisted_in_repository(client_and_server):
    """提交评价后可从 server.review_repo 读到完整记录。"""
    from datetime import datetime

    client, server = client_and_server
    task_id = _create_completed_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4},
            "comment": "教练很专业",
        },
        headers=_auth_headers(server, "u1"),
    )

    records = server.review_repo.find_by_task(task_id)
    assert len(records) == 1
    record = records[0]
    assert record["reviewer_id"] == "u1"
    assert record["evaluatee_id"] == "coach_1"
    assert record["reviewer_role"] == "STUDENT"
    assert record["ratings"]["teaching_score"] == 5
    assert isinstance(record["created_at"], datetime)


def test_reviews_are_shared_across_app_instances(client_and_server):
    """评价存在仓储里：同一 server 重新建 app 仍能读到（模拟进程重启后读库）。"""
    from fastapi.testclient import TestClient

    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig

    client, server = client_and_server
    task_id = _create_completed_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5},
            "comment": "好评",
        },
        headers=_auth_headers(server, "u1"),
    )

    new_client = TestClient(create_app(server, TransportConfig(jwt_secret="test-secret")))
    resp = new_client.get(
        f"/api/v1/escort/orders/{task_id}/reviews",
        headers=_auth_headers(server, "u1"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["comment"] == "好评"
    assert data[0]["created_at"].endswith("+00:00")


def test_in_memory_review_repository_rejects_duplicate_role():
    """仓储层兜底唯一约束：同一订单同一角色只能评价一次。"""
    import pytest

    from umcp_core.shared.review.repository import InMemoryReviewRepository

    repo = InMemoryReviewRepository()
    base = {
        "review_id": "rev_1",
        "task_id": "task_1",
        "reviewer_id": "u1",
        "reviewer_role": "STUDENT",
        "evaluatee_id": "coach_1",
        "ratings": {"overall": 5},
        "comment": "",
    }
    repo.save(dict(base))
    with pytest.raises(ValueError):
        repo.save({**base, "review_id": "rev_2"})
    assert len(repo.find_by_task("task_1")) == 1

