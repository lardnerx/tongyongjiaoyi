"""deals / trust / events router 集成测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from umcp_core.core.domain import DomainTag
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.resource import Resource, ResourceStatus
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
