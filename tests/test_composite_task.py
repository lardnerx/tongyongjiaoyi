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
