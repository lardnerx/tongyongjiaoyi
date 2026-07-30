"""Prometheus metrics 集成测试。"""

from __future__ import annotations

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


def _make_app() -> FastAPI:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    server.register_match_strategy("ride", _StubMatchStrategy())
    server.resource_repo.save(_StubResource())
    config = TransportConfig(jwt_secret="metrics-secret")
    return create_app(server, config)


class TestMetricsEndpoint:
    """/metrics 端点应返回 Prometheus 格式文本。"""

    def test_metrics_endpoint_returns_prometheus_format(self):
        """/metrics 应返回 200 且 content-type 为 text/plain。"""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        # 应包含 HELP/TYPE 行（prometheus 标准格式）
        body = resp.text
        assert "# HELP" in body
        assert "# TYPE" in body

    def test_metrics_increments_request_count(self):
        """HTTP 请求应使 http_requests_total 计数器递增。"""
        app = _make_app()
        client = TestClient(app)
        # 先打一次 /metrics 拿基线
        base_resp = client.get("/metrics")
        base_count = _extract_counter_total(base_resp.text, "http_requests_total")
        # 打一次 /api/v1/health
        client.get("/api/v1/health")
        # 再查 /metrics
        after_resp = client.get("/metrics")
        after_count = _extract_counter_total(after_resp.text, "http_requests_total")
        # 至少递增（health + metrics 两次 + 至少1）
        assert after_count > base_count

    def test_metrics_records_request_duration(self):
        """HTTP 请求应被 http_request_duration_seconds 直方图记录。"""
        app = _make_app()
        client = TestClient(app)
        # 打一次触发记录
        client.get("/api/v1/health")
        resp = client.get("/metrics")
        # 应包含 duration 指标
        assert "http_request_duration_seconds" in resp.text
        # 应有 _bucket/_sum/_count 等 histogram 指标行
        assert "http_request_duration_seconds_bucket" in resp.text
        assert "http_request_duration_seconds_count" in resp.text


def _extract_counter_total(body: str, metric_name: str) -> float:
    """从 prometheus 文本中提取某 counter 的总和（非 label 行）。"""
    total = 0.0
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        if line.startswith(metric_name + " ") or line.startswith(metric_name + "{"):
            # 形如：metric_name 12.0  或  metric_name{label="x"} 5.0
            parts = line.split()
            if len(parts) >= 2:
                try:
                    total += float(parts[-1])
                except ValueError:
                    continue
    return total
