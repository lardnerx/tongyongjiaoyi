"""P2-10/12 接入主链路验证：ResourceRegistry / L6 / 信任聚合 / CompositeTask。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from umcp_core.core.deal import Deal
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.layers.l2 import RepositoryResourceRegistry
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.layers.l5 import WeightedSumTrustEngine
from umcp_core.layers.l6 import IntelligenceModule, Prediction
from umcp_core.layers.l7 import ArbitrationPolicy, ArbitrationResult
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService
from umcp_core.transport.errors import register_exception_handlers
from umcp_core.transport.routers import register_routers


class _StubResource(Resource):
    def __init__(self, resource_id: str, domain: str = "ride") -> None:
        super().__init__(
            supplier_id=f"supplier_{resource_id}",
            domain_tag=DomainTag.of(domain),
            resource_id=resource_id,
        )

    def resource_type(self) -> str:
        return "stub"


class _RecordingMatchStrategy(InstantMatch):
    def __init__(self) -> None:
        super().__init__()
        self.captured: list[str] = []

    def execute(self, task, candidates):
        self.captured = [r.resource_id for r in candidates]
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=self.captured[0] if self.captured else None,
            candidates=self.captured,
        )


class _ReversingIntelligence(IntelligenceModule):
    """用于验证 L6 接入：把候选顺序整体反转。"""

    def predict(self, context):  # pragma: no cover - 接口占位
        return Prediction(target=context.domain, value=0.0, confidence=0.0)

    def recommend(self, task, pool):
        return list(reversed(pool))

    def detect_anomaly(self, event):  # pragma: no cover - 接口占位
        return None


def _make_server() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    return server


def _make_app(server: UMCPServer) -> FastAPI:
    app = FastAPI()
    app.state.server = server
    app.state.jwt_service = JwtService(secret="test-secret")
    register_routers(app)
    register_exception_handlers(app)
    return app


def _login(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"credential_type": "phone", "token": "13800000000"},
    )
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


class TestResourceRegistryWiring:
    def test_registry_auto_bound_with_repositories(self) -> None:
        server = _make_server()
        assert isinstance(server.resource_registry, RepositoryResourceRegistry)

    def test_register_and_unregister_through_registry(self) -> None:
        server = _make_server()
        resource = _StubResource("res_1")

        server.resource_registry.register(resource)
        assert resource.status == ResourceStatus.IDLE
        assert [r.resource_id for r in server.available_resources("ride")] == ["res_1"]

        server.resource_registry.unregister("res_1")
        assert server.available_resources("ride") == []

    def test_custom_registry_not_overwritten(self) -> None:
        class _CustomRegistry(RepositoryResourceRegistry):
            pass

        server = _make_server()
        custom = _CustomRegistry(server.resource_repo)
        server.set_resource_registry(custom)
        server.use_in_memory_repositories()
        assert server.resource_registry is custom


class TestIntelligenceWiring:
    def test_match_candidates_uses_l6_recommend(self) -> None:
        server = _make_server()
        server.resource_registry.register(_StubResource("res_1"))
        server.resource_registry.register(_StubResource("res_2"))
        server.set_intelligence_module(_ReversingIntelligence())

        task = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        assert [r.resource_id for r in server.match_candidates(task)] == [
            "res_2",
            "res_1",
        ]

    def test_publish_and_match_passes_recommended_order(self) -> None:
        server = _make_server()
        strategy = _RecordingMatchStrategy()
        server.register_match_strategy("ride", strategy)
        server.resource_registry.register(_StubResource("res_1"))
        server.resource_registry.register(_StubResource("res_2"))
        server.set_intelligence_module(_ReversingIntelligence())

        task = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        server.publish_and_match(task)

        assert strategy.captured == ["res_2", "res_1"]
        assert task.status == TaskStatus.COMPLETED


class TestTrustEvaluationPersistence:
    def test_evaluation_updates_and_persists_profile(self) -> None:
        server = _make_server()
        server.register_trust_engine("ride", WeightedSumTrustEngine(dimensions=["overall"]))
        client = TestClient(_make_app(server))
        headers = _login(client)

        resp = client.post(
            "/api/v1/trust/evaluations",
            json={
                "evaluator_id": "u1",
                "evaluatee_id": "u2",
                "task_id": "task_1",
                "ratings": {"overall": 4.0},
                "domain_tag": "ride",
            },
            headers=headers,
        )
        assert resp.status_code == 200

        profile = client.get("/api/v1/trust/profiles/u2", headers=headers).json()["data"]
        assert profile["overall_score"] == 4.0
        assert profile["domain_tag"] == "ride"

        aggregated = client.get(
            "/api/v1/trust/profiles/u2/aggregate", headers=headers
        ).json()["data"]
        assert aggregated["score"] == 4.0
        assert aggregated["domains"] == ["ride"]


class TestDisputeArbitration:
    @staticmethod
    def _disputed_deal(server: UMCPServer) -> Deal:
        deal = Deal(
            task_id="task_1",
            resource_id="res_1",
            demander_id="u1",
            supplier_id="u2",
        )
        deal.activate()
        server.deal_repo.save(deal)
        return deal

    def test_dispute_produces_l7_proposal_and_arbitrate_applies_it(self) -> None:
        server = _make_server()
        deal = self._disputed_deal(server)
        client = TestClient(_make_app(server))
        headers = _login(client)

        resp = client.post(
            f"/api/v1/deals/{deal.deal_id}/dispute",
            json={"reason": "服务未完成", "evidence": {"photo": "x.jpg"}},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["deal_status"] == "disputed"
        assert data["outcome"] == "cancelled"  # 默认策略：发起人胜诉
        stored = server.deal_repo.find_by_id(deal.deal_id).metadata["dispute"]
        assert stored["reason"] == "服务未完成"
        assert stored["evidence"] == {"photo": "x.jpg"}
        assert stored["initiator_id"]
        assert stored["arbitration"]["outcome"] == "cancelled"

        resp = client.post(
            f"/api/v1/deals/{deal.deal_id}/arbitrate", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["outcome"] == "cancelled"
        assert data["deal_status"] == "cancelled"
        assert server.deal_repo.find_by_id(deal.deal_id).status == "cancelled"

    def test_custom_policy_outcome_is_applied(self) -> None:
        class _CompletedPolicy(ArbitrationPolicy):
            def arbitrate(self, dispute):
                return ArbitrationResult(
                    dispute_id=dispute.dispute_id,
                    outcome="completed",
                    penalty=5.0,
                    reason="自定义策略：服务有效",
                )

        server = _make_server()
        server.rule_engine.set_arbitration_policy(_CompletedPolicy())
        deal = self._disputed_deal(server)
        client = TestClient(_make_app(server))
        headers = _login(client)

        client.post(f"/api/v1/deals/{deal.deal_id}/dispute", headers=headers)
        resp = client.post(
            f"/api/v1/deals/{deal.deal_id}/arbitrate", headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["outcome"] == "completed"
        assert data["penalty"] == 5.0
        assert data["deal_status"] == "completed"

    def test_arbitrate_without_dispute_is_rejected(self) -> None:
        server = _make_server()
        deal = self._disputed_deal(server)
        client = TestClient(_make_app(server))
        headers = _login(client)

        resp = client.post(
            f"/api/v1/deals/{deal.deal_id}/arbitrate", headers=headers
        )

        assert resp.json()["code"] != 0


class TestCompositeTaskApi:
    def test_create_composite_task_runs_dag(self) -> None:
        server = _make_server()
        server.register_match_strategy("ride", _RecordingMatchStrategy())
        server.resource_registry.register(_StubResource("res_ride"))
        client = TestClient(_make_app(server))
        headers = _login(client)

        resp = client.post(
            "/api/v1/tasks/composite",
            json={
                "demander_id": "u1",
                "domain_tag": "trip",
                "subtasks": [
                    {"key": "pickup", "domain_tag": "ride", "title": "接人"},
                    {"key": "deliver", "domain_tag": "ride", "title": "送达"},
                ],
                "dependencies": {"deliver": ["pickup"]},
            },
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == TaskStatus.COMPLETED
        assert [s["key"] for s in data["subtasks"]] == ["pickup", "deliver"]
        assert all(s["status"] == TaskStatus.COMPLETED for s in data["subtasks"])

    def test_composite_rejects_unknown_dependency(self) -> None:
        server = _make_server()
        server.register_match_strategy("ride", _RecordingMatchStrategy())
        client = TestClient(_make_app(server))
        headers = _login(client)

        resp = client.post(
            "/api/v1/tasks/composite",
            json={
                "demander_id": "u1",
                "domain_tag": "trip",
                "subtasks": [{"key": "pickup", "domain_tag": "ride"}],
                "dependencies": {"pickup": ["missing"]},
            },
            headers=headers,
        )

        assert resp.status_code == 409 or resp.json()["code"] != 0
