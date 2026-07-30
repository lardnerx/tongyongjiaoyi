"""deals / trust / events router 集成测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from umcp_core.core.domain import DomainTag
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService
from umcp_core.transport.errors import register_exception_handlers
from umcp_core.transport.routers import register_routers


class _StubResource(Resource):
    def __init__(self) -> None:
        super().__init__(
            supplier_id="supplier_1",
            domain_tag=DomainTag.of("ride"),
            resource_id="res_1",
        )
        self.status = ResourceStatus.IDLE

    def resource_type(self) -> str:
        return "stub"


class _StubMatchStrategy(InstantMatch):
    def execute(self, task, candidates):
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id="res_1",
            candidates=[r.resource_id for r in candidates],
        )


def _make_app() -> FastAPI:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    server.register_match_strategy("ride", _StubMatchStrategy())
    server.resource_repo.save(_StubResource())

    jwt_service = JwtService(secret="test-secret")
    app = FastAPI()
    app.state.server = server
    app.state.jwt_service = jwt_service
    register_routers(app)
    register_exception_handlers(app)
    return app


def _login_token(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"credential_type": "phone", "token": "13800000000"},
    )
    return resp.json()["data"]["access_token"]


class TestDeals:
    def test_create_deal(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "res_1",
                "demander_id": "u1",
                "supplier_id": "sup1",
                "final_amount": 100.0,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "pending"

    def test_get_deal_by_id(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        create_resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "res_1",
                "demander_id": "u1",
                "supplier_id": "sup1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        deal_id = create_resp.json()["data"]["deal_id"]
        resp = client.get(
            f"/api/v1/deals/{deal_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["deal_id"] == deal_id

    def test_activate_deal(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        create_resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "res_1",
                "demander_id": "u1",
                "supplier_id": "sup1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        deal_id = create_resp.json()["data"]["deal_id"]
        resp = client.post(
            f"/api/v1/deals/{deal_id}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_complete_deal(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        create_resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "res_1",
                "demander_id": "u1",
                "supplier_id": "sup1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        deal_id = create_resp.json()["data"]["deal_id"]
        client.post(
            f"/api/v1/deals/{deal_id}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.post(
            f"/api/v1/deals/{deal_id}/complete",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestTrust:
    def test_get_profile_unknown_user(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.get(
            "/api/v1/trust/profiles/u_unknown",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 未注册的 trust_engine 返回空 profile 或 404
        assert resp.status_code in (200, 404)

    def test_get_aggregate_score(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.get(
            "/api/v1/trust/profiles/u1/aggregate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "score" in resp.json()["data"]


class TestEvents:
    def test_list_events(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        # 触发一些事件（登录已触发，再创建任务）
        client.post(
            "/api/v1/tasks",
            json={"demander_id": "u1", "domain_tag": "ride"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.get(
            "/api/v1/events?page=1&size=20",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] >= 1


class TestDealEventEmission:
    """Deal 状态变更应通过 EventBus 发布对应事件。"""

    def test_activate_emits_deal_paid(self):
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.activate()
        events = [e for e in bus.history() if e.type == EventType.DEAL_PAID]
        assert len(events) == 1
        assert events[0].payload["deal_id"] == deal.deal_id
        assert events[0].payload["task_id"] == "t1"
        assert events[0].payload["demander_id"] == "d1"
        assert events[0].payload["supplier_id"] == "s1"

    def test_complete_emits_deal_completed(self):
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.activate()
        deal.complete()
        events = [e for e in bus.history() if e.type == EventType.DEAL_COMPLETED]
        assert len(events) == 1

    def test_open_dispute_emits_deal_disputed(self):
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.activate()
        deal.open_dispute()
        events = [e for e in bus.history() if e.type == EventType.DEAL_DISPUTED]
        assert len(events) == 1

    def test_cancel_emits_deal_cancelled(self):
        """cancel() 应发布 DEAL_CANCELLED 事件。"""
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.cancel()
        events = [e for e in bus.history() if e.type == EventType.DEAL_CANCELLED]
        assert len(events) == 1
        assert events[0].payload["deal_id"] == deal.deal_id

    def test_resolve_emits_deal_resolved(self):
        """resolve() 应发布 DEAL_RESOLVED 事件。"""
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.activate()
        deal.open_dispute()
        deal.resolve(outcome="completed")
        events = [e for e in bus.history() if e.type == EventType.DEAL_RESOLVED]
        assert len(events) == 1
        assert events[0].payload["deal_id"] == deal.deal_id

    def test_deal_without_event_bus_is_silent(self):
        """未绑定 event_bus 时，状态变更不应抛异常。"""
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        # 不调用 bind_event_bus
        deal.activate()
        deal.complete()
        # 无异常即通过


class TestDealRouterEventPublishing:
    """deals router 应在创建交易时发布 DEAL_CREATED 事件。"""

    def test_create_deal_emits_deal_created_event(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        # 从 app.state.server 拿到 event_bus 引用
        server = app.state.server
        # 创建 deal
        resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "r1",
                "demander_id": "d1",
                "supplier_id": "s1",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        # 验证 DEAL_CREATED 事件已发布
        events = server.event_bus.history()
        created_events = [e for e in events if e.type.value == "deal.created"]
        assert len(created_events) == 1
        assert created_events[0].payload["task_id"] == "t1"
        assert created_events[0].payload["demander_id"] == "d1"

    def test_activate_deal_emits_deal_paid_event(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        # 创建 deal
        create_resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "r1",
                "demander_id": "d1",
                "supplier_id": "s1",
            },
            headers=headers,
        )
        deal_id = create_resp.json()["data"]["deal_id"]
        server = app.state.server
        # 激活前清空 history 便于断言
        server.event_bus.clear()
        # 激活
        client.post(f"/api/v1/deals/{deal_id}/activate", headers=headers)
        events = server.event_bus.history()
        paid_events = [e for e in events if e.type.value == "deal.paid"]
        assert len(paid_events) == 1
        assert paid_events[0].payload["deal_id"] == deal_id


class TestDealCancelResolveRouter:
    """deals router 的 cancel/resolve/dispute 端点测试。"""

    def _create_and_activate_deal(self, client, headers) -> str:
        """创建并激活 deal，返回 deal_id。"""
        create_resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "r1",
                "demander_id": "d1",
                "supplier_id": "s1",
            },
            headers=headers,
        )
        deal_id = create_resp.json()["data"]["deal_id"]
        client.post(f"/api/v1/deals/{deal_id}/activate", headers=headers)
        return deal_id

    def test_cancel_deal_endpoint(self):
        """POST /deals/{id}/cancel 应取消交易并发布事件。"""
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        deal_id = self._create_and_activate_deal(client, headers)
        server = app.state.server
        server.event_bus.clear()
        # 取消
        resp = client.post(f"/api/v1/deals/{deal_id}/cancel", headers=headers)
        assert resp.status_code == 200
        # 验证状态
        query = client.get(f"/api/v1/deals/{deal_id}", headers=headers)
        assert query.json()["data"]["status"] == "cancelled"
        # 验证事件
        events = server.event_bus.history()
        cancelled_events = [e for e in events if e.type.value == "deal.cancelled"]
        assert len(cancelled_events) == 1
        assert cancelled_events[0].payload["deal_id"] == deal_id

    def test_cancel_terminal_deal_returns_409(self):
        """对终态交易调用 cancel 应返回 409。"""
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        deal_id = self._create_and_activate_deal(client, headers)
        # 先完成
        client.post(f"/api/v1/deals/{deal_id}/complete", headers=headers)
        # 再取消应 409
        resp = client.post(f"/api/v1/deals/{deal_id}/cancel", headers=headers)
        assert resp.status_code == 409

    def test_dispute_then_resolve_deal_endpoint(self):
        """POST /deals/{id}/dispute → /deals/{id}/resolve 完整争议流程。"""
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        deal_id = self._create_and_activate_deal(client, headers)
        server = app.state.server
        server.event_bus.clear()
        # 发起争议
        dispute_resp = client.post(f"/api/v1/deals/{deal_id}/dispute", headers=headers)
        assert dispute_resp.status_code == 200
        # 解决争议（outcome=completed）
        resolve_resp = client.post(
            f"/api/v1/deals/{deal_id}/resolve",
            json={"outcome": "completed"},
            headers=headers,
        )
        assert resolve_resp.status_code == 200
        # 验证最终状态
        query = client.get(f"/api/v1/deals/{deal_id}", headers=headers)
        assert query.json()["data"]["status"] == "completed"
        # 验证事件
        events = server.event_bus.history()
        disputed_events = [e for e in events if e.type.value == "deal.disputed"]
        resolved_events = [e for e in events if e.type.value == "deal.resolved"]
        assert len(disputed_events) == 1
        assert len(resolved_events) == 1

    def test_resolve_non_disputed_deal_returns_409(self):
        """对非争议状态交易调用 resolve 应返回 409。"""
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        deal_id = self._create_and_activate_deal(client, headers)
        # 直接 resolve（未争议）应 409
        resp = client.post(
            f"/api/v1/deals/{deal_id}/resolve",
            json={"outcome": "completed"},
            headers=headers,
        )
        assert resp.status_code == 409
