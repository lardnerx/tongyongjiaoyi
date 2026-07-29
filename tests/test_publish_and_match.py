"""UMCPServer.publish_and_match 单元测试。"""

from __future__ import annotations

import pytest

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer


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


def _make_server() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.register_match_strategy("ride", _StubMatchStrategy())
    server.resource_repo.save(_StubResource())
    return server


class TestPublishAndMatch:
    def test_publish_and_match_standard_task_completes(self):
        server = _make_server()
        task = StandardTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
        )
        server.publish_and_match(task)
        assert task.status == TaskStatus.COMPLETED
        assert task.assigned_resource_id == "res_1"

    def test_publish_and_match_composite_delegates_to_execute_composite(self):
        server = _make_server()
        sub = StandardTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
        )
        sub.task_id = "sub_a"
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub],
        )
        server.publish_and_match(composite)
        assert composite.status == TaskStatus.COMPLETED
        assert sub.status == TaskStatus.COMPLETED

    def test_publish_and_match_no_match_cancels(self):
        class _NoMatchStrategy(InstantMatch):
            def execute(self, task, candidates):
                return MatchResult(task_id=task.task_id)

        server = UMCPServer()
        server.use_in_memory_repositories()
        server.register_match_strategy("ride", _NoMatchStrategy())
        task = StandardTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
        )
        server.publish_and_match(task)
        assert task.status == TaskStatus.CANCELLED

    def test_publish_and_match_no_strategy_raises(self):
        server = UMCPServer()
        server.use_in_memory_repositories()
        task = StandardTask(
            demander_id="u1",
            domain_tag=DomainTag.of("unknown_domain"),
        )
        with pytest.raises(RuntimeError, match="未注册匹配策略"):
            server.publish_and_match(task)
