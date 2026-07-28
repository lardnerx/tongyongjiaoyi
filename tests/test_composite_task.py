"""CompositeTask 单元测试。"""

from __future__ import annotations

import pytest

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import CustomTask, StandardTask, TaskStatus


def _make_subtask(task_id: str, domain: str = "ride") -> StandardTask:
    task = StandardTask(
        demander_id="user_001",
        domain_tag=DomainTag.of(domain),
    )
    task.task_id = task_id
    return task


def _make_custom_subtask(task_id: str, domain: str = "ride") -> CustomTask:
    task = CustomTask(
        demander_id="user_001",
        domain_tag=DomainTag.of(domain),
    )
    task.task_id = task_id
    return task


class TestCompositeTaskConstruction:
    def test_composite_task_construction(self):
        sub_a = _make_subtask("sub_a")
        sub_b = _make_subtask("sub_b")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
            dependencies={"sub_b": ["sub_a"]},
        )
        assert composite.demander_id == "user_001"
        assert len(composite.subtasks) == 2
        assert composite.dependencies == {"sub_b": ["sub_a"]}
        assert composite.status == TaskStatus.DRAFT

    def test_composite_task_type(self):
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[],
        )
        assert composite.task_type() == "composite"

    def test_sync_to_package_fields(self):
        std_sub = _make_subtask("std_1")
        cus_sub = _make_custom_subtask("cus_1")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[std_sub, cus_sub],
        )
        assert composite.standard_sub_tasks == [std_sub]
        assert composite.custom_sub_task == cus_sub


class TestDagValidation:
    def test_dag_validation_no_cycle(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        sub_c = _make_subtask("c")
        # a -> b -> c (c 依赖 b，b 依赖 a)，无环
        CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"b": ["a"], "c": ["b"]},
        )  # 不抛异常即通过

    def test_dag_validation_cycle_detected(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        with pytest.raises(ValueError, match="环"):
            CompositeTask(
                demander_id="user_001",
                domain_tag=DomainTag.of("composite"),
                subtasks=[sub_a, sub_b],
                dependencies={"a": ["b"], "b": ["a"]},
            )

    def test_dag_validation_self_loop(self):
        sub_a = _make_subtask("a")
        with pytest.raises(ValueError, match="自身"):
            CompositeTask(
                demander_id="user_001",
                domain_tag=DomainTag.of("composite"),
                subtasks=[sub_a],
                dependencies={"a": ["a"]},
            )

    def test_dag_validation_missing_ref(self):
        sub_a = _make_subtask("a")
        with pytest.raises(ValueError, match="不在子任务列表中"):
            CompositeTask(
                demander_id="user_001",
                domain_tag=DomainTag.of("composite"),
                subtasks=[sub_a],
                dependencies={"a": ["nonexistent"]},
            )

    def test_dag_validation_missing_key(self):
        sub_a = _make_subtask("a")
        with pytest.raises(ValueError, match="不在子任务列表中"):
            CompositeTask(
                demander_id="user_001",
                domain_tag=DomainTag.of("composite"),
                subtasks=[sub_a],
                dependencies={"nonexistent": ["a"]},
            )


class TestDagQuery:
    def test_ready_subtasks_no_deps(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
        )
        ready = composite.ready_subtasks()
        assert len(ready) == 2
        assert {s.task_id for s in ready} == {"a", "b"}

    def test_ready_subtasks_with_deps(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
            dependencies={"b": ["a"]},
        )
        # 初始：a 就绪，b 未就绪
        ready = composite.ready_subtasks()
        assert {s.task_id for s in ready} == {"a"}
        # a 完成后：b 就绪
        sub_a.publish()
        sub_a.assign_to("res_1")
        sub_a.start_execution()
        sub_a.complete()
        ready = composite.ready_subtasks()
        assert {s.task_id for s in ready} == {"b"}

    def test_ready_subtasks_skip_non_draft(self):
        sub_a = _make_subtask("a")
        sub_a.publish()  # DRAFT → MATCHING
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        ready = composite.ready_subtasks()
        assert len(ready) == 0

    def test_descendants_direct(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
            dependencies={"b": ["a"]},
        )
        assert composite.descendants("a") == ["b"]
        assert composite.descendants("b") == []

    def test_descendants_transitive(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        sub_c = _make_subtask("c")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"b": ["a"], "c": ["b"]},
        )
        assert set(composite.descendants("a")) == {"b", "c"}
        assert composite.descendants("c") == []

    def test_descendants_no_downstream(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
            dependencies={"b": ["a"]},
        )
        # b 是叶子节点
        assert composite.descendants("b") == []


from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType


def _make_composite_with_bus(
    subtasks: list,
    dependencies: dict | None = None,
) -> tuple[CompositeTask, EventBus]:
    bus = EventBus()
    composite = CompositeTask(
        demander_id="user_001",
        domain_tag=DomainTag.of("composite"),
        subtasks=subtasks,
        dependencies=dependencies or {},
    )
    composite.bind_event_bus(bus)
    return composite, bus


def _complete_subtask(task: StandardTask) -> None:
    """推进子任务到终态 COMPLETED（需经过完整生命周期）。"""
    task.publish()
    task.assign_to("res_1")
    task.start_execution()
    task.complete()


class TestEventDrivenStateTransition:
    def test_on_subtask_completed_all_done(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite, bus = _make_composite_with_bus([sub_a, sub_b])

        # 模拟子任务完成 + 桥接事件
        _complete_subtask(sub_a)
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_COMPLETED)
        assert composite.status == TaskStatus.DRAFT  # 还有 b 未完成

        _complete_subtask(sub_b)
        composite.emit_subtask_event(sub_b, EventType.SUBTASK_COMPLETED)
        assert composite.status == TaskStatus.COMPLETED

        # 验证 COMPOSITE_COMPLETED 事件
        composite_events = [
            e for e in bus.history() if e.type == EventType.COMPOSITE_COMPLETED
        ]
        assert len(composite_events) == 1

    def test_on_subtask_cancelled_propagates(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite, bus = _make_composite_with_bus(
            [sub_a, sub_b], dependencies={"b": ["a"]}
        )

        # a 取消 → 应传播到 b
        sub_a.cancel()
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_CANCELLED)

        assert sub_a.status == TaskStatus.CANCELLED
        assert sub_b.status == TaskStatus.CANCELLED
        assert composite.status == TaskStatus.CANCELLED

    def test_on_subtask_cancelled_no_dep_siblings_continue(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")  # 与 a 无依赖
        sub_c = _make_subtask("c")
        composite, bus = _make_composite_with_bus(
            [sub_a, sub_b, sub_c], dependencies={"c": ["a"]}
        )

        # a 取消 → c 应取消，b 不受影响
        sub_a.cancel()
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_CANCELLED)

        assert sub_a.status == TaskStatus.CANCELLED
        assert sub_b.status == TaskStatus.DRAFT  # 无依赖兄弟不受影响
        assert sub_c.status == TaskStatus.CANCELLED
        assert composite.status == TaskStatus.CANCELLED

    def test_fail_composite_when_any_cancelled(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite, bus = _make_composite_with_bus([sub_a, sub_b])

        _complete_subtask(sub_a)
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_COMPLETED)

        sub_b.cancel()
        composite.emit_subtask_event(sub_b, EventType.SUBTASK_CANCELLED)

        assert composite.status == TaskStatus.CANCELLED
        failed_events = [
            e for e in bus.history() if e.type == EventType.COMPOSITE_FAILED
        ]
        assert len(failed_events) == 1

    def test_idempotent_complete(self):
        sub_a = _make_subtask("a")
        composite, bus = _make_composite_with_bus([sub_a])

        _complete_subtask(sub_a)
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_COMPLETED)
        assert composite.status == TaskStatus.COMPLETED

        # 重复触发不应报错
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_COMPLETED)
        assert composite.status == TaskStatus.COMPLETED

    def test_idempotent_fail(self):
        sub_a = _make_subtask("a")
        composite, bus = _make_composite_with_bus([sub_a])

        sub_a.cancel()
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_CANCELLED)
        assert composite.status == TaskStatus.CANCELLED

        # 重复触发不应报错
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_CANCELLED)
        assert composite.status == TaskStatus.CANCELLED

    def test_event_filter_by_composite_task_id(self):
        # 两个独立的 composite 共享同一 bus
        sub_a1 = _make_subtask("a1")
        sub_a2 = _make_subtask("a2")
        bus = EventBus()

        comp1 = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a1],
        )
        comp1.bind_event_bus(bus)

        comp2 = CompositeTask(
            demander_id="u2",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a2],
        )
        comp2.bind_event_bus(bus)

        # 完成 a1，应只触发 comp1 完成，不影响 comp2
        _complete_subtask(sub_a1)
        comp1.emit_subtask_event(sub_a1, EventType.SUBTASK_COMPLETED)

        assert comp1.status == TaskStatus.COMPLETED
        assert comp2.status == TaskStatus.DRAFT  # a2 未完成
