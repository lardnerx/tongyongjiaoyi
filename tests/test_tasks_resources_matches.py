"""tasks / resources / matches router 集成测试。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService
from umcp_core.transport.errors import register_exception_handlers
from umcp_core.transport.routers import register_routers


class _StubResource(Resource):
    def __init__(self, resource_id: str = "res_1", domain: str = "ride") -> None:
        super().__init__(
            supplier_id="supplier_1",
            domain_tag=DomainTag.of(domain),
            resource_id=resource_id,
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


def _make_app() -> tuple[FastAPI, UMCPServer]:
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
    return app, server


def _login_token(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"credential_type": "phone", "token": "13800000000"},
    )
    return resp.json()["data"]["access_token"]


class TestTasks:
    def test_create_standard_task(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.post(
            "/api/v1/tasks",
            json={
                "demander_id": "u1",
                "domain_tag": "ride",
                "title": "打车去机场",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "completed"
        assert body["data"]["assigned_resource_id"] == "res_1"

    def test_get_task_by_id(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        create_resp = client.post(
            "/api/v1/tasks",
            json={"demander_id": "u1", "domain_tag": "ride"},
            headers={"Authorization": f"Bearer {token}"},
        )
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["task_id"] == task_id

    def test_get_tasks_list(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        client.post(
            "/api/v1/tasks",
            json={"demander_id": "u1", "domain_tag": "ride"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.get(
            "/api/v1/tasks?page=1&size=20",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] >= 1
        assert len(body["items"]) >= 1

    def test_get_task_not_found(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.get(
            "/api/v1/tasks/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 2001

    def test_cancel_completed_task_returns_409(self):
        """已完成任务 cancel 应返回 409。"""
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        # 用 ride 创建任务（会立即完成匹配）
        create_resp = client.post(
            "/api/v1/tasks",
            json={"demander_id": "u1", "domain_tag": "ride"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 200  # 强制校验创建成功
        task_id = create_resp.json()["data"]["task_id"]
        # 已完成的任务 cancel 应返回 409
        cancel_resp = client.post(
            f"/api/v1/tasks/{task_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cancel_resp.status_code == 409
        assert cancel_resp.json()["code"] == 2002  # IllegalStateError

    def test_create_task_no_strategy_returns_409(self):
        """domain 无匹配策略应返回 409（而非 500）。"""
        # 构造一个未注册任何匹配策略的 server（match_strategy 保持 None，
        # 否则 register_match_strategy 会设置单值兜底，导致未知 domain 回退命中）
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.set_auth_provider(PhoneAuthProvider())
        jwt_service = JwtService(secret="test-secret")
        app = FastAPI()
        app.state.server = server
        app.state.jwt_service = jwt_service
        register_routers(app)
        register_exception_handlers(app)
        client = TestClient(app)
        token = _login_token(client)
        resp = client.post(
            "/api/v1/tasks",
            json={"demander_id": "u1", "domain_tag": "no_such_domain"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == 2002


class TestResources:
    def test_register_resource(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.post(
            "/api/v1/resources",
            json={
                "supplier_id": "sup_new",
                "domain_tag": "ride",
                "resource_type": "stub",
                "capabilities": [{"type": "skill", "name": "driving"}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["resource_id"]

    def test_get_resources_list(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.get(
            "/api/v1/resources?domain_tag=ride",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] >= 1

    def test_get_resource_by_id(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.get(
            "/api/v1/resources/res_1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["resource_id"] == "res_1"

    def test_update_resource_status(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        resp = client.post(
            "/api/v1/resources/res_1/status",
            json={"status": "busy"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestMatches:
    def test_trigger_match(self):
        app, _ = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        # 先创建任务（会立即完成匹配）
        create_resp = client.post(
            "/api/v1/tasks",
            json={"demander_id": "u1", "domain_tag": "ride"},
            headers={"Authorization": f"Bearer {token}"},
        )
        task_id = create_resp.json()["data"]["task_id"]
        # 手动触发匹配
        resp = client.post(
            "/api/v1/matches",
            json={"task_id": task_id, "domain_tag": "ride"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 任务已终态，触发匹配可能失败或返回已有结果
        assert resp.status_code in (200, 409)
