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
    """SchedulerService 应注册 RealtimeCancelWorker。"""
    _, app = app_client
    worker_names = [w.name for w in app.state.scheduler._workers]
    assert "realtime_cancel" in worker_names
