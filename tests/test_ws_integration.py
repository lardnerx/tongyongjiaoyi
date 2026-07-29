"""WebSocket 集成测试：事件触发 → 推送验证。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig


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


def _make_app() -> tuple:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    server.register_match_strategy("ride", _StubMatchStrategy())
    server.resource_repo.save(_StubResource())
    config = TransportConfig(jwt_secret="ws-test-secret")
    app = create_app(server, config)
    return app, server


def _login(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"credential_type": "phone", "token": "13800000000"},
    )
    return resp.json()["data"]["access_token"]


class TestWsEventPush:
    def test_ws_connection_and_event_history(self):
        """WS 连接成功 + 触发事件后历史中有事件。

        注意：当前 Task._emit 发布的事件 payload 仅含 task_id，不含 demander_id，
        因此 WS 桥接函数 _extract_user_ids 返回空列表，不会触发实际推送。
        此测试验证 WS 连接成功 + 事件已发布到 EventBus 历史（推送机制由
        test_ws_manager.py 的 TestEventBridge 单元测试覆盖）。
        """
        import jwt as pyjwt

        app, server = _make_app()
        client = TestClient(app)
        token = _login(client)

        # 解码 JWT 获取真实 user_id（PhoneAuthProvider 生成随机 user_id，非手机号）
        payload = pyjwt.decode(token, "ws-test-secret", algorithms=["HS256"])
        user_id = payload["sub"]

        with client.websocket_connect(f"/api/v1/ws/events?token={token}") as ws:
            # 连接成功；用真实 user_id 作为 demander_id 创建任务
            client.post(
                "/api/v1/tasks",
                json={"demander_id": user_id, "domain_tag": "ride"},
                headers={"Authorization": f"Bearer {token}"},
            )
            # 验证事件已发布到 EventBus
            events = server.event_bus.history()
            types = [e.type.value for e in events]
            assert "task.published" in types

    def test_ws_rejects_connection_without_token(self):
        """无 token 连接 WS 应被拒绝。"""
        app, _ = _make_app()
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/ws/events"):
                pass

    def test_ws_rejects_connection_with_invalid_token(self):
        """无效 token 连接 WS 应被拒绝。"""
        app, _ = _make_app()
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/ws/events?token=invalid"):
                pass

    def test_ws_ping_pong(self):
        """WS 客户端发 ping，服务端应回 pong。"""
        app, _ = _make_app()
        client = TestClient(app)
        token = _login(client)

        with client.websocket_connect(f"/api/v1/ws/events?token={token}") as ws:
            ws.send_text("ping")
            msg = ws.receive_json()
            assert msg["type"] == "pong"
