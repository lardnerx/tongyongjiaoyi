"""验证 cancel_order 端点按规则扣信用分。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _auth_headers(server, user_id="student1"):
    """生成已认证请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_realtime_task(server, user_id="student1"):
    from plugins.escort_driving.tasks import EscortTask
    from umcp_core.core.domain import DomainTag

    task = EscortTask(
        demander_id=user_id,
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="REALTIME",
    )
    task.bind_event_bus(server.event_bus)
    task.publish_for_claim()
    server.task_repo.save(task)
    return task


def _create_scheduled_task(server, user_id="student1", scheduled_at=None):
    from plugins.escort_driving.tasks import EscortTask
    from umcp_core.core.domain import DomainTag

    task = EscortTask(
        demander_id=user_id,
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="SCHEDULED",
        scheduled_at=scheduled_at or (datetime.utcnow() + timedelta(hours=2)),
    )
    server.task_repo.save(task)
    return task


def test_cancel_realtime_no_penalty(app_client):
    """实时单手动取消不扣信用分。"""
    client, server = app_client
    task = _create_realtime_task(server)
    headers = _auth_headers(server)

    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "cancelled"
    assert body["data"]["cancel_penalty"] == 0.0


def test_cancel_scheduled_far_in_advance_low_penalty(app_client):
    """预约单提前 25 小时取消，扣 0.2 分（命中 hours_before=24 档）。"""
    client, server = app_client
    scheduled_at = datetime.utcnow() + timedelta(hours=25)
    task = _create_scheduled_task(server, scheduled_at=scheduled_at)
    headers = _auth_headers(server)

    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 0.2


def test_cancel_scheduled_close_to_time_high_penalty(app_client):
    """预约单提前 1 小时取消，扣 2.0 分（命中 hours_before=0 档）。"""
    client, server = app_client
    scheduled_at = datetime.utcnow() + timedelta(hours=1)
    task = _create_scheduled_task(server, scheduled_at=scheduled_at)
    headers = _auth_headers(server)

    # 先给学员一个正向评分（4.0），否则扣分后仍为 0 无法验证
    from umcp_core.layers.l5.trust import Evaluation
    engine = server.trust_engine_for("escort")
    engine.record_evaluation(Evaluation(
        evaluator_id="coach1",
        evaluatee_id=task.demander_id,
        task_id="t1",
        ratings={"teaching_ability": 4.0, "patience": 4.0, "safety_record": 4.0},
        comment="",
    ))

    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 2.0

    profile = engine.evaluate(task.demander_id)
    # 原 4.0 - 2.0 = 2.0
    assert profile.overall_score == 2.0


def test_cancel_scheduled_with_deal_triggers_refund(app_client):
    """预约单已支付定金后取消，应触发退款。"""
    client, server = app_client
    scheduled_at = datetime.utcnow() + timedelta(hours=25)
    task = _create_scheduled_task(server, scheduled_at=scheduled_at)
    headers = _auth_headers(server)

    # 模拟已选教练并支付（直接构造 deal + payment）
    from umcp_core.core.deal import Deal

    payment_service = server.payment_service

    deal = Deal(
        task_id=task.task_id,
        resource_id="coach_res_1",
        demander_id=task.demander_id,
        supplier_id="coach1",
    )
    deal.bind_event_bus(server.event_bus)
    deal.final_amount = 100.0
    server.deal_repo.save(deal)

    # 创建并确认一笔定金支付
    intent = payment_service.create_payment(
        deal_id=deal.deal_id,
        user_id=task.demander_id,
        amount=30.0,
        payment_type="DEPOSIT",
    )
    payment_service.confirm_payment(payment_id=intent.payment_id)

    # 取消订单
    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers=headers,
    )
    assert resp.status_code == 200

    # 验证退款（payment 记录状态变为 refunded）
    records = payment_service.repo.find_by_deal(deal.deal_id)
    refunded = [r for r in records if r["status"] == "refunded"]
    assert len(refunded) >= 1, "定金应被退款"


def test_cancel_nonexistent_task_returns_404(app_client):
    """取消不存在的订单返回 404。"""
    client, server = app_client
    headers = _auth_headers(server)

    resp = client.post(
        "/api/v1/escort/orders/nonexistent/cancel",
        headers=headers,
    )
    assert resp.status_code == 404


def test_cancel_terminal_task_returns_409(app_client):
    """取消已终态的订单返回 409。"""
    client, server = app_client
    task = _create_realtime_task(server)
    task.bind_event_bus(server.event_bus)
    task.cancel()
    server.task_repo.save(task)

    headers = _auth_headers(server)
    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers=headers,
    )
    assert resp.status_code == 409
