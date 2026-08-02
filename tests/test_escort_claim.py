"""实时单抢单流程测试。"""
from __future__ import annotations

import threading

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

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
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


def _create_order(client, server, demander_id="u1"):
    """创建实时单并返回 task_id。"""
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
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, demander_id),
    )
    return resp.json()["data"]["task_id"]


def test_create_realtime_order_returns_published(client_and_server):
    """实时单下单后状态为 published（抢单模式，不自动分配）。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    resp = client.get(
        f"/api/v1/escort/orders/{task_id}",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "published"
    assert data["order_type"] == "REALTIME"


def test_claim_order_success(client_and_server):
    """教练抢单成功，状态变为 assigned。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "assigned"
    assert data["assigned_resource_id"] == "coach_1"


def test_claim_already_assigned_fails(client_and_server):
    """已被抢的订单无法再次抢单。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_2"},
        headers=_auth_headers(server, "coach_2", roles=["supplier"]),
    )
    # IllegalStateError → HTTP 409 Conflict（订单已被抢，与当前状态冲突）
    assert resp2.status_code == 409


def test_check_in_transitions_to_in_progress(client_and_server):
    """教练签到，状态变为 in_progress。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "in_progress"


def test_check_out_transitions_to_completed(client_and_server):
    """教练签退，状态变为 completed。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"


# ---------- 越权校验测试 ----------


def test_claim_for_other_coach_fails(client_and_server):
    """越权抢单：coach_1 不能为 coach_2 抢单，返回 403。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_2"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 403


def test_check_in_for_other_coach_fails(client_and_server):
    """越权签到：coach_2 不能为 coach_1 签到，返回 403。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_2", roles=["supplier"]),
    )
    assert resp.status_code == 403


def test_check_out_for_other_coach_fails(client_and_server):
    """越权签退：coach_2 不能为 coach_1 签退，返回 403。"""
    client, server = client_and_server
    task_id = _create_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_2", roles=["supplier"]),
    )
    assert resp.status_code == 403


# ---------- 并发抢单测试 ----------


def test_concurrent_claim_only_one_succeeds(client_and_server):
    """并发抢单：两个教练同时抢同一订单，只有一个成功（200），另一个失败（409）。

    验证 per-task_id 锁能有效串行化抢单操作，避免竞态条件。
    """
    client, server = client_and_server
    task_id = _create_order(client, server)

    # 创建两个独立 TestClient 共享同一 app（各自有独立事件循环/portal）
    app = client.app
    client_a = TestClient(app)
    client_b = TestClient(app)

    results: list[tuple[str, int]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def claim(client_x: TestClient, coach_id: str) -> None:
        try:
            barrier.wait(timeout=5)
            resp = client_x.post(
                f"/api/v1/escort/orders/{task_id}/claim",
                json={"coach_id": coach_id},
                headers=_auth_headers(server, coach_id, roles=["supplier"]),
            )
            with results_lock:
                results.append((coach_id, resp.status_code))
        except Exception as e:
            with results_lock:
                results.append((coach_id, f"error: {e}"))

    t_a = threading.Thread(target=claim, args=(client_a, "coach_1"))
    t_b = threading.Thread(target=claim, args=(client_b, "coach_2"))
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    status_codes = [r[1] for r in results]
    assert len(results) == 2, f"两个线程都应完成，实际: {results}"
    assert status_codes.count(200) == 1, (
        f"期望恰好一个抢单成功，实际: {results}"
    )
    assert status_codes.count(409) == 1, (
        f"期望恰好一个抢单失败（409），实际: {results}"
    )
