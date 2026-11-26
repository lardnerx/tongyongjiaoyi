"""验证 FastAPI lifespan 启动 SchedulerService 并注册 RealtimeCancelWorker。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.scheduler import SchedulerService


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, app


def test_scheduler_service_attached_to_app_state(app_client):
    """app.state.scheduler 应为 SchedulerService 实例。"""
    _, app = app_client
    assert hasattr(app.state, "scheduler")
    assert isinstance(app.state.scheduler, SchedulerService)


def test_realtime_cancel_worker_registered(app_client):
    """SchedulerService 应注册陪驾插件提供的 RealtimeCancelWorker。"""
    _, app = app_client
    worker_names = [w.name for w in app.state.scheduler._workers]
    assert "escort_realtime_cancel" in worker_names


def test_payment_callback_exempt_path_registered(app_client):
    """支付回调豁免路径应由插件注册到 server，而非核心硬编码。"""
    _, app = app_client
    assert "/api/v1/escort/payments/callback" in app.state.server.rate_limit_exempt_paths
