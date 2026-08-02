"""取消策略端到端集成测试。

覆盖：
1. 实时单：超时自动取消（SchedulerService 驱动）
2. 实时单：用户手动取消（无罚分）
3. 预约单：提前 25h 取消（扣 0.2 分 + 退款）
4. 预约单：提前 1h 取消（扣 2.0 分 + 退款）
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from umcp_core.layers.l5.trust import Evaluation
from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.auth import JwtService, _ClaimsDemander, _ClaimsUser
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.workers.realtime_cancel_worker import RealtimeCancelWorker


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    # 加速测试：超时 2 秒，扩展 1 秒
    server.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=2,
        updated_by="test",
        category="escort.cancel",
    )
    server.rule_config.set(
        key="escort.cancel.realtime.expand_after_seconds",
        value=1,
        updated_by="test",
        category="escort.cancel",
    )
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


def _create_realtime_order(client, server, user_id="student1") -> str:
    """通过 API 下实时单，返回 task_id。"""
    resp = client.post(
        "/api/v1/escort/orders",
        headers=_auth_headers(server, user_id),
        json={
            "demander_id": user_id,
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "auto",
            "required_skills": [],
            "duration_hours": 1,
            "order_type": "REALTIME",
        },
    )
    assert resp.status_code == 200
    return resp.json()["data"]["task_id"]


@pytest.mark.asyncio
async def test_e2e_realtime_auto_cancel(app_client):
    """实时单超时后应被 SchedulerService 自动取消。"""
    client, server = app_client
    task_id = _create_realtime_order(client, server)

    # 手动驱动 worker（不依赖 lifespan 中的 1 秒间隔）
    worker = RealtimeCancelWorker()
    # 第 0 秒：未超时
    await worker.run(context={"server": server})
    assert server.task_repo.find_by_id(task_id).status == "published"

    # 等待 2.5 秒（超过 2 秒超时）
    await asyncio.sleep(2.5)
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task_id)
    assert refreshed.status == "cancelled"


def test_e2e_realtime_manual_cancel_no_penalty(app_client):
    """实时单手动取消不扣信用分。"""
    client, server = app_client
    task_id = _create_realtime_order(client, server)

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/cancel",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "cancelled"
    assert body["cancel_penalty"] == 0.0


def test_e2e_scheduled_cancel_far_advance_low_penalty(app_client):
    """预约单提前 25h 取消，扣 0.2 分。"""
    client, server = app_client
    scheduled_at = (datetime.utcnow() + timedelta(hours=25)).isoformat()

    # 下预约单
    resp = client.post(
        "/api/v1/escort/orders",
        headers=_auth_headers(server),
        json={
            "demander_id": "student1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "auto",
            "required_skills": [],
            "duration_hours": 1,
            "order_type": "SCHEDULED",
            "scheduled_at": scheduled_at,
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]

    # 取消
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/cancel",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 0.2


def test_e2e_scheduled_cancel_close_high_penalty(app_client):
    """预约单提前 1h 取消，扣 2.0 分。"""
    client, server = app_client
    scheduled_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()

    # 先给学员正向评分（4.0）
    engine = server.trust_engine_for("escort")
    engine.record_evaluation(Evaluation(
        evaluator_id="coach1",
        evaluatee_id="student1",
        task_id="t1",
        ratings={"teaching_ability": 4.0, "patience": 4.0, "safety_record": 4.0},
        comment="",
    ))

    resp = client.post(
        "/api/v1/escort/orders",
        headers=_auth_headers(server),
        json={
            "demander_id": "student1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "auto",
            "required_skills": [],
            "duration_hours": 1,
            "order_type": "SCHEDULED",
            "scheduled_at": scheduled_at,
        },
    )
    task_id = resp.json()["data"]["task_id"]

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/cancel",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 2.0

    # 信用分应为 4.0 - 2.0 = 2.0
    profile = engine.evaluate("student1")
    assert profile.overall_score == 2.0
