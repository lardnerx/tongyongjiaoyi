"""UMCPServer 复合任务编排单元测试。"""

from __future__ import annotations

import pytest

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.events.types import EventType
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer


class _StubResource(Resource):
    """测试用资源桩。"""

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
    """测试用匹配策略桩，始终匹配 res_1。"""

    def execute(self, task, candidates):
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id="res_1",
            candidates=[r.resource_id for r in candidates],
        )


def _make_server_with_strategy(domain: str = "ride") -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.register_match_strategy(domain, _StubMatchStrategy())
    # 注册一个资源
    res = _StubResource(domain=domain)
    server.resource_repo.save(res)
    return server


def _make_subtask(task_id: str, domain: str = "ride") -> StandardTask:
    task = StandardTask(
        demander_id="user_001",
        domain_tag=DomainTag.of(domain),
    )
    task.task_id = task_id
    return task


class TestExecuteComposite:
    def test_execute_composite_rejects_non_composite(self):
        server = _make_server_with_strategy()
        task = StandardTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
        )
        with pytest.raises(TypeError):
            server.execute_composite(task)  # type: ignore[arg-type]

    def test_execute_composite_rejects_non_draft(self):
        server = _make_server_with_strategy()
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[_make_subtask("a")],
        )
        composite.publish()
        with pytest.raises(RuntimeError, match="不允许执行"):
            server.execute_composite(composite)

    def test_execute_composite_publishes_parent(self):
        # 注意：父任务在 execute_composite 后立即 COMPLETED 是因为
        # 子任务被同步执行器（_execute_subtask_by_domain）立即完成，
        # 进而触发 SUBTASK_COMPLETED 桥接 → 父任务状态推进至 COMPLETED。
        server = _make_server_with_strategy()
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[_make_subtask("a")],
        )
        server.execute_composite(composite)
        assert composite.status == TaskStatus.COMPLETED

    def test_execute_composite_binds_event_bus(self):
        server = _make_server_with_strategy()
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[_make_subtask("a")],
        )
        server.execute_composite(composite)
        assert composite._event_bus is server.event_bus

    def test_dispatch_ready_subtasks_publishes_subtasks(self):
        server = _make_server_with_strategy()
        sub_a = _make_subtask("a")
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        server.execute_composite(composite)
        # 子任务应被默认执行器立即完成
        assert sub_a.status == TaskStatus.COMPLETED


class TestExecuteSubtaskByDomain:
    def test_execute_subtask_by_domain_uses_domain_strategy(self):
        server = _make_server_with_strategy("ride")
        sub = _make_subtask("a", domain="ride")
        server._execute_subtask_by_domain(sub)
        assert sub.status == TaskStatus.COMPLETED
        assert sub.assigned_resource_id == "res_1"

    def test_execute_subtask_no_match_cancels(self):
        # 注册一个永远不匹配的策略
        class _NoMatchStrategy(InstantMatch):
            def execute(self, task, candidates):
                return MatchResult(task_id=task.task_id)

        server = UMCPServer()
        server.use_in_memory_repositories()
        server.register_match_strategy("ride", _NoMatchStrategy())
        sub = _make_subtask("a", domain="ride")
        server._execute_subtask_by_domain(sub)
        assert sub.status == TaskStatus.CANCELLED


class TestBridgeEvent:
    def test_bridge_task_completed_to_subtask_event(self):
        server = _make_server_with_strategy()
        sub_a = _make_subtask("a")
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        server.execute_composite(composite)
        # 子任务被默认执行器完成，应触发桥接 → SUBTASK_COMPLETED → 父任务完成
        assert composite.status == TaskStatus.COMPLETED

    def test_bridge_task_cancelled_to_subtask_cancelled(self):
        # 用无匹配策略使子任务取消
        class _NoMatchStrategy(InstantMatch):
            def execute(self, task, candidates):
                return MatchResult(task_id=task.task_id)

        server = UMCPServer()
        server.use_in_memory_repositories()
        server.register_match_strategy("ride", _NoMatchStrategy())
        sub_a = _make_subtask("a", domain="ride")
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        server.execute_composite(composite)
        # 子任务无匹配 → cancel → 桥接 → SUBTASK_CANCELLED → 父任务失败
        assert sub_a.status == TaskStatus.CANCELLED
        assert composite.status == TaskStatus.CANCELLED


class TestCustomExecutor:
    def test_register_subtask_executor_overrides_default(self):
        server = _make_server_with_strategy()
        executed: list[str] = []

        def custom_executor(subtask):
            executed.append(subtask.task_id)
            subtask.publish()
            subtask.assign_to("custom_res")
            subtask.start_execution()
            # 故意不 complete，验证自定义执行器被调用

        server.register_subtask_executor("ride", custom_executor)

        sub_a = _make_subtask("a", domain="ride")
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        server.execute_composite(composite)
        assert executed == ["a"]
        assert sub_a.status == TaskStatus.IN_PROGRESS
