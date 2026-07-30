"""create_app 应用工厂测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
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


def _make_server() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    server.register_match_strategy("ride", _StubMatchStrategy())
    server.resource_repo.save(_StubResource())
    return server


def _make_app() -> FastAPI:
    server = _make_server()
    config = TransportConfig(jwt_secret="test-secret")
    return create_app(server, config)


class TestAppFactory:
    def test_health_endpoint(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ok"

    def test_openapi_docs_available(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_cors_headers(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 204)

    def test_ws_endpoint_accepts_connection(self):
        app = _make_app()
        client = TestClient(app)
        # 先登录拿 token
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        token = login_resp.json()["data"]["access_token"]
        # 连接 WS
        with client.websocket_connect(
            f"/api/v1/ws/events?token={token}"
        ) as ws:
            # 连接成功，不主动断开（TestClient 退出上下文自动断开）
            pass

    def test_ws_rejects_invalid_token(self):
        app = _make_app()
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/ws/events?token=invalid"):
                pass


class TestLifespanResourceRelease:
    """验证 lifespan shutdown 释放 server 资源。"""

    def test_shutdown_calls_server_stop_and_dispose(self):
        """lifespan 结束时应调用 server.stop() 和 server.dispose()。"""
        from umcp_core.layers.l1 import PhoneAuthProvider
        from umcp_core.server import UMCPServer
        from umcp_core.transport.app import create_app
        from umcp_core.transport.config import TransportConfig

        server = UMCPServer()
        server.use_in_memory_repositories()
        server.set_auth_provider(PhoneAuthProvider())
        config = TransportConfig(jwt_secret="test-secret")
        app = create_app(server, config)

        import unittest.mock as mock
        with mock.patch.object(server, "stop") as m_stop, \
             mock.patch.object(server, "dispose") as m_dispose:
            with TestClient(app):
                pass
            m_stop.assert_called_once()
            m_dispose.assert_called_once()


class TestLoggingSetup:
    """验证 _setup_logging 加载 logging.conf。"""

    def test_setup_logging_loads_config_when_exists(self):
        """logging.conf 存在时，_setup_logging 应配置 umcp_core logger。"""
        import logging
        from umcp_core.transport.app import _setup_logging

        _setup_logging()
        logger = logging.getLogger("umcp_core")
        assert logger.level == logging.INFO

    def test_setup_logging_no_raise_when_config_absent(self, tmp_path, monkeypatch):
        """logging.conf 不存在时，_setup_logging 不应抛异常。"""
        from umcp_core.transport import app as app_module

        # 模拟 logging.conf 不存在的路径
        monkeypatch.setattr(app_module, "_LOG_CONF_PATH", tmp_path / "nonexistent.conf")
        app_module._setup_logging()  # 不抛异常即通过
