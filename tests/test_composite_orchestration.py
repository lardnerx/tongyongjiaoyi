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
        assert composite.is_event_bus_bound()

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
        # 直接调用私有方法以隔离测试 _execute_subtask_by_domain 的路由逻辑，
        # 不经过 execute_composite 的 DAG 派发流程。
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
        # 直接调用私有方法以隔离测试无匹配时的取消逻辑。
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

    def test_bridge_unsubscribed_after_composite_terminal(self):
        """复合任务到达终态后，桥接函数应从 EventBus 取消订阅，避免闭包泄漏。"""
        from umcp_core.events.types import EventType as _ET

        server = _make_server_with_strategy()
        sub_a = _make_subtask("a")
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        # 记录订阅前后的 handler 数量（TASK_COMPLETED 与 TASK_CANCELLED 桥接均应取消订阅）
        handlers_before = server.event_bus.handler_count(_ET.TASK_COMPLETED)
        handlers_before_cancelled = server.event_bus.handler_count(_ET.TASK_CANCELLED)
        server.execute_composite(composite)
        # 复合任务已 COMPLETED，桥接函数应已取消订阅
        assert composite.status == TaskStatus.COMPLETED
        handlers_after = server.event_bus.handler_count(_ET.TASK_COMPLETED)
        assert handlers_after == handlers_before, (
            f"桥接函数未取消订阅：before={handlers_before}, after={handlers_after}"
        )
        handlers_after_cancelled = server.event_bus.handler_count(_ET.TASK_CANCELLED)
        assert handlers_after_cancelled == handlers_before_cancelled, (
            f"TASK_CANCELLED 桥接函数未取消订阅："
            f"before={handlers_before_cancelled}, after={handlers_after_cancelled}"
        )

    def test_bridge_unsubscribed_after_composite_failed(self):
        """复合任务失败后，桥接函数应从 EventBus 取消订阅。"""
        from umcp_core.events.types import EventType as _ET

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
        handlers_before = server.event_bus.handler_count(_ET.TASK_COMPLETED)
        handlers_before_cancelled = server.event_bus.handler_count(_ET.TASK_CANCELLED)
        server.execute_composite(composite)
        # 复合任务已 CANCELLED，桥接函数应已取消订阅
        assert composite.status == TaskStatus.CANCELLED
        handlers_after = server.event_bus.handler_count(_ET.TASK_COMPLETED)
        assert handlers_after == handlers_before, (
            f"桥接函数未取消订阅：before={handlers_before}, after={handlers_after}"
        )
        handlers_after_cancelled = server.event_bus.handler_count(_ET.TASK_CANCELLED)
        assert handlers_after_cancelled == handlers_before_cancelled, (
            f"TASK_CANCELLED 桥接函数未取消订阅："
            f"before={handlers_before_cancelled}, after={handlers_after_cancelled}"
        )

    def test_bridge_downstream_cancel_propagation_with_dependencies(self):
        """带 DAG 依赖的下游取消传播。

        场景：子任务 A（无依赖）、子任务 B（依赖 A）。
        取消 A → A 发出 TASK_CANCELLED → 桥接转 SUBTASK_CANCELLED →
        父任务 _on_subtask_cancelled 级联取消 B（DRAFT→CANCELLED）→
        B 也桥接为 SUBTASK_CANCELLED → 复合任务最终 cancelled。
        """
        from umcp_core.events.types import EventType as _ET

        server = _make_server_with_strategy()

        # 自定义执行器：将子任务推进到 IN_PROGRESS 但不 complete，
        # 以便手动触发 cancel 验证级联传播。
        def custom_executor(subtask):
            subtask.publish()
            subtask.assign_to("custom_res")
            subtask.start_execution()

        server.register_subtask_executor("ride", custom_executor)

        sub_a = _make_subtask("a", domain="ride")
        sub_b = _make_subtask("b", domain="ride")
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
            dependencies={"b": ["a"]},
        )

        # 收集 SUBTASK_CANCELLED 事件以验证级联传播
        cancelled_events: list = []
        server.event_bus.subscribe(
            _ET.SUBTASK_CANCELLED,
            lambda e: cancelled_events.append(e),
        )

        server.execute_composite(composite)

        # A 就绪并被派发（IN_PROGRESS），B 因依赖 A 而阻塞（DRAFT）
        assert sub_a.status == TaskStatus.IN_PROGRESS
        assert sub_b.status == TaskStatus.DRAFT

        # 取消 A：A 发出 TASK_CANCELLED → 桥接转 SUBTASK_CANCELLED → 级联取消 B
        sub_a.cancel()

        # A 与 B 均被取消
        assert sub_a.status == TaskStatus.CANCELLED
        assert sub_b.status == TaskStatus.CANCELLED
        # 复合任务最终 cancelled
        assert composite.status == TaskStatus.CANCELLED
        # 桥接将 A 的取消转为 SUBTASK_CANCELLED，级联将 B 的取消也转为 SUBTASK_CANCELLED
        cancelled_subtask_ids = [
            e.payload.get("subtask_id") for e in cancelled_events
        ]
        assert "a" in cancelled_subtask_ids, "A 的取消未桥接为 SUBTASK_CANCELLED"
        assert "b" in cancelled_subtask_ids, "B 的级联取消未桥接为 SUBTASK_CANCELLED"


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
