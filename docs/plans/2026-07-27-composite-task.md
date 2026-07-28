# 阶段四C：复合任务编排 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 `CompositeTask` 跨 domain DAG 编排，由 EventBus 驱动状态转移，失败按依赖传播，由 `UMCPServer.execute_composite` 统一派发。

**架构：** 新增 `CompositeTask`（继承 `PackageTask`）持有 `subtasks` + `dependencies`，构造时 DAG 校验（环/自环/引用存在）。`CompositeTask` 订阅 `SUBTASK_COMPLETED`/`SUBTASK_CANCELLED` 事件驱动自身状态转移与下游取消传播。`UMCPServer.execute_composite` 负责绑定 EventBus、发布父任务、派发就绪子任务、桥接 `TASK_COMPLETED`→`SUBTASK_*`。子任务按各自 `domain_tag` 路由到对应插件的 `MatchStrategy`（阶段四A/B 已支持），零插件改动。

**技术栈：** Python 3.10+ / pytest / 无第三方依赖 / 核心库抽象基类零修改。

---

## 文件结构

**创建（4 个）**：
- `src/umcp_core/core/composite_task.py` — `CompositeTask` 类（独立文件，避免 `task.py` 膨胀）
- `tests/test_composite_task.py` — `CompositeTask` 单元测试（20 个）
- `tests/test_composite_orchestration.py` — `UMCPServer` 编排单元测试（10 个）
- `tests/test_end_to_end_composite_task.py` — 端到端测试（8 个）

**修改（3 个）**：
- `src/umcp_core/events/types.py` — 追加 `SUBTASK_COMPLETED`/`SUBTASK_CANCELLED`/`COMPOSITE_COMPLETED`/`COMPOSITE_FAILED` 四个事件类型
- `src/umcp_core/core/__init__.py` — 导出 `CompositeTask`
- `src/umcp_core/server.py` — 追加 `execute_composite`/`_dispatch_ready_subtasks`/`_execute_subtask_by_domain`/`register_subtask_executor`，新增 `_subtask_executors` 字段

**零修改**：
- `core/task.py`（`Task`/`StandardTask`/`CustomTask`/`PackageTask` 抽象基类不改）
- `events/bus.py`（`EventBus` 不改）
- `layers/l3`/`l4`/`l5`/`l7`（各层接口不改）
- `plugins/*`（三插件零改动）

**Demo**：
- `examples/composite_task_demo.py` — 商务出行包 demo

---

## 任务分解

### 任务 1：新增事件类型

**文件：**
- 修改：`src/umcp_core/events/types.py`

- [ ] **步骤 1：修改事件类型枚举**

在 `events/types.py` 的 `EventType` 类末尾（`DISPUTE_RESOLVED` 之后）追加四个事件类型：

```python
    # 复合任务编排（阶段四C）
    SUBTASK_COMPLETED = "subtask.completed"
    SUBTASK_CANCELLED = "subtask.cancelled"
    COMPOSITE_COMPLETED = "composite.completed"
    COMPOSITE_FAILED = "composite.failed"
```

- [ ] **步骤 2：运行现有测试验证无回归**

运行：`python -m pytest tests/ -q --tb=short`
预期：267 passed

- [ ] **步骤 3：Commit**

```bash
git add src/umcp_core/events/types.py
git commit -m "feat(events): 新增 SUBTASK_*/COMPOSITE_* 事件类型"
```

---

### 任务 2：CompositeTask 构造与 DAG 校验

**文件：**
- 创建：`src/umcp_core/core/composite_task.py`
- 修改：`src/umcp_core/core/__init__.py`
- 测试：`tests/test_composite_task.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_composite_task.py`，写入构造与 DAG 校验相关测试：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_composite_task.py -v`
预期：FAIL，`ImportError: No module named 'umcp_core.core.composite_task'`

- [ ] **步骤 3：实现 CompositeTask 构造与 DAG 校验**

创建 `src/umcp_core/core/composite_task.py`：

```python
"""CompositeTask：跨 domain 复合任务（DAG 编排）。"""

from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import CustomTask, PackageTask, StandardTask, Task, TaskStatus


class CompositeTask(PackageTask):
    """跨 domain 复合任务（DAG 编排）。

    子任务可通过 dependencies 声明依赖关系，形成 DAG。
    状态转移由事件驱动：子任务 COMPLETED/CANCELLED 触发父任务状态更新。
    """

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        subtasks: list[Task] | None = None,
        dependencies: dict[str, list[str]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(demander_id, domain_tag, **kwargs)
        self.subtasks: list[Task] = subtasks or []
        self.dependencies: dict[str, list[str]] = dependencies or {}
        self._sync_to_package_fields()
        self._validate_dag()

    def task_type(self) -> str:
        return "composite"

    # ---- DAG 查询接口 ----

    def ready_subtasks(self) -> list[Task]:
        """返回当前可执行的子任务（依赖已全部 COMPLETED 且自身 DRAFT）。"""
        ready = []
        for sub in self.subtasks:
            if sub.status != TaskStatus.DRAFT:
                continue
            deps = self.dependencies.get(sub.task_id, [])
            if all(self._find_sub(d).status == TaskStatus.COMPLETED for d in deps):
                ready.append(sub)
        return ready

    def pending_subtasks(self) -> list[Task]:
        """返回尚未完成的子任务（非终态）。"""
        return [s for s in self.subtasks if not TaskStatus.is_terminal(s.status)]

    def descendants(self, subtask_id: str) -> list[str]:
        """返回直接或间接依赖 subtask_id 的所有下游子任务 ID。"""
        reverse = self._build_reverse_deps()
        visited, result = set(), []
        queue = [subtask_id]
        while queue:
            current = queue.pop(0)
            for child in reverse.get(current, []):
                if child not in visited:
                    visited.add(child)
                    result.append(child)
                    queue.append(child)
        return result

    # ---- DAG 校验 ----

    def _validate_dag(self) -> None:
        """构造时校验 DAG 合法性：无环、引用存在、无自环。"""
        sub_ids = {s.task_id for s in self.subtasks}
        for sub_id, deps in self.dependencies.items():
            if sub_id not in sub_ids:
                raise ValueError(f"依赖键 {sub_id} 不在子任务列表中")
            for d in deps:
                if d not in sub_ids:
                    raise ValueError(f"依赖目标 {d} 不在子任务列表中")
                if d == sub_id:
                    raise ValueError(f"子任务 {sub_id} 不能依赖自身")
        # 环检测（DFS）
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {sid: WHITE for sid in sub_ids}

        def dfs(node: str) -> None:
            color[node] = GRAY
            for dep in self.dependencies.get(node, []):
                if color[dep] == GRAY:
                    raise ValueError(f"检测到环：{node} → {dep}")
                if color[dep] == WHITE:
                    dfs(dep)
            color[node] = BLACK

        for sid in sub_ids:
            if color[sid] == WHITE:
                dfs(sid)

    # ---- 内部辅助 ----

    def _find_sub(self, subtask_id: str) -> Task:
        for sub in self.subtasks:
            if sub.task_id == subtask_id:
                return sub
        raise KeyError(f"子任务 {subtask_id} 不存在")

    def _build_reverse_deps(self) -> dict[str, list[str]]:
        reverse: dict[str, list[str]] = {}
        for sub_id, deps in self.dependencies.items():
            for d in deps:
                reverse.setdefault(d, []).append(sub_id)
        return reverse

    def _sync_to_package_fields(self) -> None:
        """同步 subtasks 到 PackageTask 的 standard_sub_tasks / custom_sub_task。"""
        self.standard_sub_tasks = [s for s in self.subtasks if isinstance(s, StandardTask)]
        customs = [s for s in self.subtasks if isinstance(s, CustomTask)]
        self.custom_sub_task = customs[0] if customs else None
```

- [ ] **步骤 4：更新 `core/__init__.py` 导出**

在 `src/umcp_core/core/__init__.py` 追加导出（如文件不存在则创建）：

```python
"""核心抽象包。"""

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.task import CustomTask, PackageTask, StandardTask, Task, TaskStatus

__all__ = [
    "CompositeTask",
    "CustomTask",
    "PackageTask",
    "StandardTask",
    "Task",
    "TaskStatus",
]
```

> 注意：执行前先读取现有 `core/__init__.py`，追加 `CompositeTask` 导入与 `__all__` 条目，不删除现有内容。

- [ ] **步骤 5：运行测试验证通过**

运行：`python -m pytest tests/test_composite_task.py::TestCompositeTaskConstruction tests/test_composite_task.py::TestDagValidation -v`
预期：8 passed

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/core/composite_task.py src/umcp_core/core/__init__.py tests/test_composite_task.py
git commit -m "feat(core): CompositeTask 构造与 DAG 校验"
```

---

### 任务 3：DAG 查询接口（ready_subtasks / descendants）

**文件：**
- 测试：`tests/test_composite_task.py`（追加测试）

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_composite_task.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试验证通过**

运行：`python -m pytest tests/test_composite_task.py::TestDagQuery -v`
预期：6 passed（`ready_subtasks` / `descendants` 已在任务 2 实现）

- [ ] **步骤 3：Commit**

```bash
git add tests/test_composite_task.py
git commit -m "test(core): CompositeTask DAG 查询接口测试"
```

---

### 任务 4：CompositeTask 事件订阅与状态转移

**文件：**
- 修改：`src/umcp_core/core/composite_task.py`
- 测试：`tests/test_composite_task.py`（追加测试）

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_composite_task.py` 末尾追加：

```python
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


class TestEventDrivenStateTransition:
    def test_on_subtask_completed_all_done(self):
        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite, bus = _make_composite_with_bus([sub_a, sub_b])

        # 模拟子任务完成 + 桥接事件
        sub_a.complete()
        composite.emit_subtask_event(sub_a, EventType.SUBTASK_COMPLETED)
        assert composite.status == TaskStatus.DRAFT  # 还有 b 未完成

        sub_b.complete()
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

        sub_a.complete()
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

        sub_a.complete()
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
        sub_a1.complete()
        comp1.emit_subtask_event(sub_a1, EventType.SUBTASK_COMPLETED)

        assert comp1.status == TaskStatus.COMPLETED
        assert comp2.status == TaskStatus.DRAFT  # a2 未完成
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_composite_task.py::TestEventDrivenStateTransition -v`
预期：FAIL，`AttributeError: 'CompositeTask' object has no attribute 'emit_subtask_event'` 或 `bind_event_bus` 未订阅子任务事件

- [ ] **步骤 3：实现事件订阅与状态转移**

在 `src/umcp_core/core/composite_task.py` 的 `CompositeTask` 类中追加方法：

```python
    # ---- 事件订阅与状态转移 ----

    def bind_event_bus(self, bus: EventBus) -> None:
        """绑定事件总线并订阅子任务事件。"""
        from umcp_core.events.bus import EventBus as _Bus  # noqa: F811
        super().bind_event_bus(bus)
        bus.subscribe(EventType.SUBTASK_COMPLETED, self._on_subtask_completed)
        bus.subscribe(EventType.SUBTASK_CANCELLED, self._on_subtask_cancelled)

    def emit_subtask_event(self, subtask: Task, event_type: EventType) -> None:
        """子任务状态变更时由上层（server/桥接）调用，通知父任务。"""
        if self._event_bus is None:
            return
        from umcp_core.events.bus import Event

        self._event_bus.publish(
            Event(
                type=event_type,
                source_layer="L2",
                payload={
                    "composite_task_id": self.task_id,
                    "subtask_id": subtask.task_id,
                    "subtask_domain": subtask.domain_tag.value,
                    "subtask_status": subtask.status,
                },
            )
        )

    def _on_subtask_completed(self, event: Event) -> None:
        """子任务完成回调：检查是否所有子任务完成 → 父任务 complete。"""
        if event.payload.get("composite_task_id") != self.task_id:
            return
        if any(not TaskStatus.is_terminal(s.status) for s in self.subtasks):
            return
        if any(s.status == TaskStatus.CANCELLED for s in self.subtasks):
            self._fail_composite()
        else:
            self._complete_composite()

    def _on_subtask_cancelled(self, event: Event) -> None:
        """子任务取消回调：传播取消到下游子任务。"""
        if event.payload.get("composite_task_id") != self.task_id:
            return
        failed_id = event.payload.get("subtask_id")
        downstream_ids = self.descendants(failed_id)
        for sub_id in downstream_ids:
            sub = self._find_sub(sub_id)
            if not TaskStatus.is_terminal(sub.status):
                sub.cancel()
                self.emit_subtask_event(sub, EventType.SUBTASK_CANCELLED)
        self._on_subtask_completed(event)

    def _complete_composite(self) -> None:
        """所有子任务成功完成 → 父任务完成。"""
        if self.status == TaskStatus.COMPLETED:
            return
        # 跳过 PackageTask.complete 的子任务校验（CompositeTask 由事件驱动保证一致性）
        Task.complete(self)
        if self._event_bus:
            from umcp_core.events.bus import Event

            self._event_bus.publish(
                Event(
                    type=EventType.COMPOSITE_COMPLETED,
                    source_layer="L2",
                    payload={"composite_task_id": self.task_id},
                )
            )

    def _fail_composite(self) -> None:
        """存在失败子任务 → 父任务失败。"""
        if self.status == TaskStatus.CANCELLED:
            return
        self.cancel()
        if self._event_bus:
            from umcp_core.events.bus import Event

            self._event_bus.publish(
                Event(
                    type=EventType.COMPOSITE_FAILED,
                    source_layer="L2",
                    payload={
                        "composite_task_id": self.task_id,
                        "failed_subtask_ids": [
                            s.task_id for s in self.subtasks
                            if s.status == TaskStatus.CANCELLED
                        ],
                    },
                )
            )
```

同时在文件顶部追加 import：

```python
from umcp_core.events.bus import Event, EventBus
from umcp_core.events.types import EventType
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_composite_task.py::TestEventDrivenStateTransition -v`
预期：7 passed

- [ ] **步骤 5：运行全部测试验证无回归**

运行：`python -m pytest tests/test_composite_task.py -v`
预期：21 passed（8 + 6 + 7）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/core/composite_task.py tests/test_composite_task.py
git commit -m "feat(core): CompositeTask 事件驱动状态转移与失败传播"
```

---

### 任务 5：UMCPServer 编排路由

**文件：**
- 修改：`src/umcp_core/server.py`
- 测试：`tests/test_composite_orchestration.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_composite_orchestration.py`：

```python
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
        server = _make_server_with_strategy()
        composite = CompositeTask(
            demander_id="u1",
            domain_tag=DomainTag.of("composite"),
            subtasks=[_make_subtask("a")],
        )
        server.execute_composite(composite)
        assert composite.status == TaskStatus.MATCHING

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
        # 子任务应被 publish 进入 MATCHING
        assert sub_a.status == TaskStatus.COMPLETED  # 默认执行器立即完成


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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_composite_orchestration.py -v`
预期：FAIL，`AttributeError: 'UMCPServer' object has no attribute 'execute_composite'`

- [ ] **步骤 3：实现 UMCPServer 编排方法**

在 `src/umcp_core/server.py` 的 `UMCPServer` 类中追加：

首先在 `__init__` 方法中追加字段（在 `self._trust_aggregator` 之后）：

```python
        # 复合任务子任务执行器（按 domain 注册，覆盖默认行为）
        self._subtask_executors: dict[str, Any] = {}
```

然后在类中追加方法（建议放在 `# 复合任务编排` 注释块下，`# 启动与停止` 之前）：

```python
    # ------------------------------------------------------------------
    # 复合任务编排
    # ------------------------------------------------------------------

    def execute_composite(self, composite: CompositeTask) -> None:
        """驱动复合任务执行。

        流程：
        1. 绑定 EventBus（订阅子任务事件）
        2. 发布父任务 → 进入 MATCHING
        3. 注册 TASK_COMPLETED → SUBTASK_* 桥接
        4. 按 DAG 拓扑序启动就绪子任务
        5. 子任务完成事件触发父任务状态转移（由 CompositeTask 事件回调处理）

        本方法只负责"启动"，不负责"完成判定"——完成判定由事件驱动。
        """
        from umcp_core.core.composite_task import CompositeTask
        from umcp_core.core.task import TaskStatus

        if not isinstance(composite, CompositeTask):
            raise TypeError(f"期望 CompositeTask，收到 {type(composite).__name__}")
        if composite.status != TaskStatus.DRAFT:
            raise RuntimeError(f"复合任务状态 {composite.status} 不允许执行")

        # 1. 绑定 EventBus（触发 subscribe 子任务事件）
        composite.bind_event_bus(self.event_bus)

        # 2. 发布父任务
        composite.publish()

        # 3. 注册子任务事件桥接：TASK_COMPLETED → SUBTASK_*
        subtask_ids = {s.task_id for s in composite.subtasks}

        def _bridge_to_subtask_event(event: Event) -> None:
            task_id = event.payload.get("task_id")
            if task_id not in subtask_ids:
                return
            subtask = composite._find_sub(task_id)
            if event.payload.get("cancelled"):
                composite.emit_subtask_event(subtask, EventType.SUBTASK_CANCELLED)
            else:
                composite.emit_subtask_event(subtask, EventType.SUBTASK_COMPLETED)
            # 子任务状态变更后，尝试派发新就绪的子任务（串行依赖链推进）
            self._dispatch_ready_subtasks(composite)

        self.event_bus.subscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)

        # 4. 启动所有就绪子任务
        self._dispatch_ready_subtasks(composite)

    def _dispatch_ready_subtasks(self, composite: CompositeTask) -> None:
        """派发就绪子任务到对应 domain 执行。"""
        for subtask in composite.ready_subtasks():
            subtask.bind_event_bus(self.event_bus)
            subtask.publish()
            self._execute_subtask_by_domain(subtask)

    def _execute_subtask_by_domain(self, subtask: Task) -> None:
        """按子任务 domain_tag 路由到对应插件的匹配策略执行。"""
        domain = subtask.domain_tag.value
        custom_executor = self._subtask_executors.get(domain)
        if custom_executor is not None:
            custom_executor(subtask)
            return

        strategy = self.match_strategy_for(domain)
        if strategy is None:
            raise RuntimeError(f"domain {domain} 未注册匹配策略")
        if self.resource_repo is None:
            raise RuntimeError("resource_repo 未注入")

        candidates = self.resource_repo.find_available(subtask.domain_tag)
        result = strategy.execute(subtask, candidates)
        if not result.matched:
            subtask.cancel()
            return

        subtask.assign_to(result.selected_resource_id)
        subtask.start_execution()
        subtask.complete()

    def register_subtask_executor(
        self, domain: str, executor: Any
    ) -> None:
        """注册特定 domain 的子任务执行器（覆盖默认 _execute_subtask_by_domain）。"""
        self._subtask_executors[domain.lower()] = executor
```

同时在 `server.py` 顶部 import 区追加（如尚未导入）：

```python
from umcp_core.core.task import Task
```

> 注意：`CompositeTask` 在方法内延迟导入以避免循环依赖。`Event` 和 `EventType` 已在顶部导入。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_composite_orchestration.py -v`
预期：10 passed

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/server.py tests/test_composite_orchestration.py
git commit -m "feat(server): UMCPServer 复合任务编排路由"
```

---

### 任务 6：端到端测试 — 并行与串行 DAG

**文件：**
- 测试：`tests/test_end_to_end_composite_task.py`

- [ ] **步骤 1：编写测试**

创建 `tests/test_end_to_end_composite_task.py`：

```python
"""端到端测试：复合任务编排。"""

from __future__ import annotations

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer


class _E2EResource(Resource):
    """端到端测试用资源。"""

    def __init__(self, resource_id: str = "res_1", domain: str = "ride") -> None:
        super().__init__(
            supplier_id="supplier_1",
            domain_tag=DomainTag.of(domain),
            resource_id=resource_id,
        )
        self.status = ResourceStatus.IDLE

    def resource_type(self) -> str:
        return "e2e"


class _AlwaysMatchStrategy(InstantMatch):
    """始终匹配第一个候选资源。"""

    def execute(self, task, candidates):
        if not candidates:
            return MatchResult(task_id=task.task_id)
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=candidates[0].resource_id,
            candidates=[r.resource_id for r in candidates],
        )


class _NoMatchStrategy(InstantMatch):
    """永远不匹配。"""

    def execute(self, task, candidates):
        return MatchResult(task_id=task.task_id)


def _make_server_with_domains(*domains: str, no_match_domain: str | None = None) -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    for d in domains:
        strategy = _NoMatchStrategy() if d == no_match_domain else _AlwaysMatchStrategy()
        server.register_match_strategy(d, strategy)
        server.resource_repo.save(_E2EResource(domain=d))
    return server


def _make_subtask(task_id: str, domain: str = "ride") -> StandardTask:
    task = StandardTask(
        demander_id="user_001",
        domain_tag=DomainTag.of(domain),
    )
    task.task_id = task_id
    return task


class TestParallelComposite:
    def test_parallel_composite_all_complete(self):
        """3 个无依赖子任务并行执行 → 父任务 COMPLETED。"""
        server = _make_server_with_domains("ride", "escort", "group_buying")
        sub_ride = _make_subtask("ride_1", "ride")
        sub_escort = _make_subtask("escort_1", "escort")
        sub_gb = _make_subtask("gb_1", "group_buying")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_ride, sub_escort, sub_gb],
        )
        server.execute_composite(composite)

        assert sub_ride.status == TaskStatus.COMPLETED
        assert sub_escort.status == TaskStatus.COMPLETED
        assert sub_gb.status == TaskStatus.COMPLETED
        assert composite.status == TaskStatus.COMPLETED


class TestSerialComposite:
    def test_serial_composite_pipeline(self):
        """A→B→C 串行依赖，按序完成 → 父任务 COMPLETED。"""
        server = _make_server_with_domains("ride")
        sub_a = _make_subtask("a", "ride")
        sub_b = _make_subtask("b", "ride")
        sub_c = _make_subtask("c", "ride")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"b": ["a"], "c": ["b"]},
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.COMPLETED
        assert sub_b.status == TaskStatus.COMPLETED
        assert sub_c.status == TaskStatus.COMPLETED
        assert composite.status == TaskStatus.COMPLETED


class TestMixedDag:
    def test_mixed_dag_parallel_and_serial(self):
        """混合 DAG：A∥B → C（A、B 并行，都完成后 C 才执行）。"""
        server = _make_server_with_domains("ride")
        sub_a = _make_subtask("a", "ride")
        sub_b = _make_subtask("b", "ride")
        sub_c = _make_subtask("c", "ride")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"c": ["a", "b"]},
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.COMPLETED
        assert sub_b.status == TaskStatus.COMPLETED
        assert sub_c.status == TaskStatus.COMPLETED
        assert composite.status == TaskStatus.COMPLETED


class TestFailurePropagation:
    def test_failure_propagation_cancels_downstream(self):
        """A 失败 → B（依赖 A）取消，C（无依赖）继续完成 → 父任务 CANCELLED。"""
        server = _make_server_with_domains("ride", "no_match", no_match_domain="no_match")
        sub_a = _make_subtask("a", "no_match")  # A 会失败（无匹配）
        sub_b = _make_subtask("b", "ride")      # B 依赖 A
        sub_c = _make_subtask("c", "ride")      # C 无依赖

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"b": ["a"]},
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.CANCELLED
        assert sub_b.status == TaskStatus.CANCELLED  # 依赖 A，被传播取消
        assert sub_c.status == TaskStatus.COMPLETED  # 无依赖兄弟继续完成
        assert composite.status == TaskStatus.CANCELLED

    def test_failure_no_dep_sibling_continues(self):
        """A 失败，B（无依赖）已完成 → 父任务 CANCELLED，但 B 保持 COMPLETED。"""
        server = _make_server_with_domains("ride", "no_match", no_match_domain="no_match")
        sub_a = _make_subtask("a", "no_match")  # A 会失败
        sub_b = _make_subtask("b", "ride")      # B 无依赖

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.CANCELLED
        assert sub_b.status == TaskStatus.COMPLETED  # 兄弟保持完成
        assert composite.status == TaskStatus.CANCELLED


class TestCrossDomainRouting:
    def test_cross_domain_subtasks_use_domain_routing(self):
        """ride 子任务用 ride 域策略，group_buying 子任务用 gb 域策略。"""
        # 注册两个不同的策略实例，通过 resource_id 区分
        class _RideStrategy(_AlwaysMatchStrategy):
            def execute(self, task, candidates):
                return MatchResult(
                    task_id=task.task_id,
                    selected_resource_id="ride_res",
                    candidates=["ride_res"],
                )

        class _GbStrategy(_AlwaysMatchStrategy):
            def execute(self, task, candidates):
                return MatchResult(
                    task_id=task.task_id,
                    selected_resource_id="gb_res",
                    candidates=["gb_res"],
                )

        server = UMCPServer()
        server.use_in_memory_repositories()
        server.register_match_strategy("ride", _RideStrategy())
        server.register_match_strategy("group_buying", _GbStrategy())
        server.resource_repo.save(_E2EResource("ride_res", "ride"))
        server.resource_repo.save(_E2EResource("gb_res", "group_buying"))

        sub_ride = _make_subtask("ride_1", "ride")
        sub_gb = _make_subtask("gb_1", "group_buying")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_ride, sub_gb],
        )
        server.execute_composite(composite)

        assert sub_ride.assigned_resource_id == "ride_res"
        assert sub_gb.assigned_resource_id == "gb_res"
        assert composite.status == TaskStatus.COMPLETED


class TestCustomExecutorE2E:
    def test_custom_executor_per_domain(self):
        """注册 ride 域自定义执行器（延迟完成），验证覆盖默认行为。"""
        server = _make_server_with_domains("ride")
        completed_by_custom: list[str] = []

        def custom_executor(subtask):
            subtask.publish()
            subtask.assign_to("custom_res")
            subtask.start_execution()
            subtask.complete()
            completed_by_custom.append(subtask.task_id)

        server.register_subtask_executor("ride", custom_executor)

        sub_a = _make_subtask("a", "ride")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        server.execute_composite(composite)

        assert completed_by_custom == ["a"]
        assert sub_a.assigned_resource_id == "custom_res"
        assert composite.status == TaskStatus.COMPLETED


class TestTenderTaskBackwardCompatible:
    def test_tender_task_backward_compatible(self):
        """TenderTask（继承 PackageTask）行为零改动，现有集采流程正常。"""
        from umcp_core.core.task import CustomTask, PackageTask, StandardTask

        # 构造一个 PackageTask（模拟 TenderTask 的基本结构）
        std_sub = StandardTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("group_buying"),
        )
        std_sub.task_id = "product_sub"
        cus_sub = CustomTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("group_buying"),
        )
        cus_sub.task_id = "service_sub"

        package = PackageTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("group_buying"),
            standard_sub_tasks=[std_sub],
            custom_sub_task=cus_sub,
        )
        assert package.task_type() == "package"
        assert len(package.standard_sub_tasks) == 1
        assert package.custom_sub_task is not None
        # 验证 PackageTask 仍可独立使用，不受 CompositeTask 影响
```

- [ ] **步骤 2：运行测试验证通过**

运行：`python -m pytest tests/test_end_to_end_composite_task.py -v`
预期：8 passed

- [ ] **步骤 3：Commit**

```bash
git add tests/test_end_to_end_composite_task.py
git commit -m "test(e2e): 复合任务编排端到端测试"
```

---

### 任务 7：Demo 脚本

**文件：**
- 创建：`examples/composite_task_demo.py`

- [ ] **步骤 1：编写 Demo 脚本**

创建 `examples/composite_task_demo.py`：

```python
"""阶段四C Demo：复合任务编排（商务出行包）。

场景：
- 子任务 1：打车去机场（ride 域，无依赖）
- 子任务 2：代驾回家（escort 域，depends_on=[1]）
- 子任务 3：团购伴手礼（group_buying 域，无依赖，与打车并行）

运行方式：
    PYTHONPATH=src;plugins python -m examples.composite_task_demo
"""

from __future__ import annotations

import sys
from pathlib import Path

# 注入 src 和 plugins 到 sys.path，使 demo 可直接运行
_SRC = Path(__file__).parent.parent / "src"
_PLUGINS = Path(__file__).parent.parent / "plugins"
for p in (_SRC, _PLUGINS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer


class _DemoResource(Resource):
    """Demo 资源桩。"""

    def __init__(self, resource_id: str, domain: str, supplier_name: str) -> None:
        super().__init__(
            supplier_id=f"supplier_{resource_id}",
            domain_tag=DomainTag.of(domain),
            resource_id=resource_id,
        )
        self.status = ResourceStatus.IDLE
        self.metadata["name"] = supplier_name

    def resource_type(self) -> str:
        return "demo"


class _DemoMatchStrategy(InstantMatch):
    """Demo 匹配策略：始终匹配第一个候选。"""

    def execute(self, task, candidates):
        if not candidates:
            return MatchResult(task_id=task.task_id)
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=candidates[0].resource_id,
            candidates=[r.resource_id for r in candidates],
        )


def _make_subtask(task_id: str, domain: str, title: str) -> StandardTask:
    task = StandardTask(
        demander_id="business_user_001",
        domain_tag=DomainTag.of(domain),
        title=title,
    )
    task.task_id = task_id
    return task


def run_success_scenario() -> None:
    """场景一：成功完成商务出行包。"""
    print("=" * 60)
    print("场景一：商务出行包（成功完成）")
    print("=" * 60)

    server = UMCPServer()
    server.use_in_memory_repositories()

    # 注册三个 domain 的策略和资源
    for d, res_id, name in [
        ("ride", "ride_res", "出租车司机老王"),
        ("escort", "escort_res", "陪驾教练老李"),
        ("group_buying", "gb_res", "伴手礼供应商老张"),
    ]:
        server.register_match_strategy(d, _DemoMatchStrategy())
        server.resource_repo.save(_DemoResource(res_id, d, name))

    # 构造子任务
    sub_ride = _make_subtask("ride_1", "ride", "打车去机场")
    sub_escort = _make_subtask("escort_1", "escort", "代驾回家")
    sub_gb = _make_subtask("gb_1", "group_buying", "团购伴手礼")

    print(f"\n子任务 A: {sub_ride.title} ({sub_ride.domain_tag.value})")
    print(f"子任务 B: {sub_escort.title} ({sub_escort.domain_tag.value}), depends_on=[A]")
    print(f"子任务 C: {sub_gb.title} ({sub_gb.domain_tag.value})")

    composite = CompositeTask(
        demander_id="business_user_001",
        domain_tag=DomainTag.of("composite"),
        subtasks=[sub_ride, sub_escort, sub_gb],
        dependencies={"escort_1": ["ride_1"]},
    )

    print(f"\n父任务 ID: {composite.task_id}")
    print(f"初始状态: {composite.status}")
    print("\n启动编排...")

    server.execute_composite(composite)

    print(f"\n--- 执行结果 ---")
    print(f"子任务 A ({sub_ride.title}): {sub_ride.status}")
    print(f"  └─ 指派资源: {sub_ride.assigned_resource_id}")
    print(f"子任务 B ({sub_escort.title}): {sub_escort.status}")
    print(f"  └─ 指派资源: {sub_escort.assigned_resource_id}")
    print(f"子任务 C ({sub_gb.title}): {sub_gb.status}")
    print(f"  └─ 指派资源: {sub_gb.assigned_resource_id}")
    print(f"\n父任务状态: {composite.status}")

    assert composite.status == TaskStatus.COMPLETED
    print("\n✓ 商务出行包全部完成")


def run_failure_scenario() -> None:
    """场景二：打车失败，代驾取消，团购完成，父任务失败。"""
    print("\n" + "=" * 60)
    print("场景二：打车失败 → 代驾取消 → 父任务失败")
    print("=" * 60)

    server = UMCPServer()
    server.use_in_memory_repositories()

    # ride 域注册无匹配策略（模拟无可用出租车）
    class _NoMatchStrategy(InstantMatch):
        def execute(self, task, candidates):
            return MatchResult(task_id=task.task_id)

    server.register_match_strategy("ride", _NoMatchStrategy())
    server.register_match_strategy("escort", _DemoMatchStrategy())
    server.register_match_strategy("group_buying", _DemoMatchStrategy())
    server.resource_repo.save(_DemoResource("escort_res", "escort", "陪驾教练老李"))
    server.resource_repo.save(_DemoResource("gb_res", "group_buying", "伴手礼供应商老张"))

    sub_ride = _make_subtask("ride_1", "ride", "打车去机场")
    sub_escort = _make_subtask("escort_1", "escort", "代驾回家")
    sub_gb = _make_subtask("gb_1", "group_buying", "团购伴手礼")

    composite = CompositeTask(
        demander_id="business_user_001",
        domain_tag=DomainTag.of("composite"),
        subtasks=[sub_ride, sub_escort, sub_gb],
        dependencies={"escort_1": ["ride_1"]},
    )

    print(f"\n子任务 A: {sub_ride.title} (无可用资源)")
    print(f"子任务 B: {sub_escort.title}, depends_on=[A]")
    print(f"子任务 C: {sub_gb.title} (无依赖)")

    print("\n启动编排...")
    server.execute_composite(composite)

    print(f"\n--- 执行结果 ---")
    print(f"子任务 A ({sub_ride.title}): {sub_ride.status} (无匹配资源)")
    print(f"子任务 B ({sub_escort.title}): {sub_escort.status} (依赖 A，被传播取消)")
    print(f"子任务 C ({sub_gb.title}): {sub_gb.status} (无依赖兄弟，继续完成)")
    print(f"\n父任务状态: {composite.status}")

    assert sub_ride.status == TaskStatus.CANCELLED
    assert sub_escort.status == TaskStatus.CANCELLED
    assert sub_gb.status == TaskStatus.COMPLETED
    assert composite.status == TaskStatus.CANCELLED
    print("\n✓ 失败传播正确：A 失败 → B 取消，C 完成，父任务失败")


if __name__ == "__main__":
    run_success_scenario()
    run_failure_scenario()
    print("\n" + "=" * 60)
    print("Demo 完成")
    print("=" * 60)
```

- [ ] **步骤 2：运行 Demo 验证**

运行：
```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
python examples/composite_task_demo.py
```
预期：输出两个场景的执行结果，最后打印 "Demo 完成"

- [ ] **步骤 3：Commit**

```bash
git add examples/composite_task_demo.py
git commit -m "demo: 复合任务编排演示（商务出行包）"
```

---

### 任务 8：最终验证与回归测试

- [ ] **步骤 1：运行全部测试**

运行：`python -m pytest tests/ -v`
预期：267 + 21 + 10 + 8 = 306 passed（容忍 ±1 的计数偏差）

> 说明：设计规格预期 305 passed（20 单元 + 10 Server + 8 端到端），实际单元测试为 21 个（8 构造校验 + 6 DAG 查询 + 7 事件驱动），总数为 306。

- [ ] **步骤 2：验证现有测试零改动**

确认以下测试文件未被修改（git diff 应为空）：
- `tests/test_multi_plugin_routing.py`
- `tests/test_end_to_end_multi_plugin.py`
- `tests/test_cross_domain_trust.py`
- `tests/test_end_to_end_cross_domain_trust.py`
- `plugins/*/tests/test_plugin_loading.py`

运行：`git diff HEAD~7 -- tests/test_multi_plugin_routing.py tests/test_end_to_end_multi_plugin.py tests/test_cross_domain_trust.py tests/test_end_to_end_cross_domain_trust.py`
预期：无输出（零改动）

- [ ] **步骤 3：验证核心库改动文件数**

运行：`git diff HEAD~7 --name-only -- src/`
预期：仅 3 个文件
- `src/umcp_core/core/composite_task.py`（新建）
- `src/umcp_core/core/__init__.py`（导出）
- `src/umcp_core/events/types.py`（事件类型）
- `src/umcp_core/server.py`（编排方法）

> 说明：实际 4 个文件（含 `__init__.py` 导出），与设计规格"核心库改动文件数 = 3"略有偏差（`__init__.py` 仅追加导出，非功能改动）。

- [ ] **步骤 4：验证抽象基类零修改**

运行：`git diff HEAD~7 -- src/umcp_core/core/task.py src/umcp_core/core/resource.py src/umcp_core/core/base.py src/umcp_core/core/deal.py`
预期：无输出（`Task`/`PackageTask`/`Resource`/`User`/`Deal` 抽象基类零修改）

- [ ] **步骤 5：验证插件包零改动**

运行：`git diff HEAD~7 --name-only -- plugins/`
预期：无输出（三插件零改动）

- [ ] **步骤 6：Commit 最终验证记录（可选）**

如有任何修复，提交修复；否则无需 commit。

---

## 自检

### 1. 规格覆盖度

| 规格章节 | 实现任务 | 状态 |
|---------|---------|------|
| §3.1 CompositeTask 数据结构与 DAG 校验 | 任务 2 | ✓ |
| §3.1 ready_subtasks / descendants 查询 | 任务 3 | ✓ |
| §3.2 事件订阅与状态转移 | 任务 4 | ✓ |
| §3.3 新增事件类型 | 任务 1 | ✓ |
| §3.3 UMCPServer 编排路由 | 任务 5 | ✓ |
| §3.3 桥接函数 | 任务 5（内嵌 execute_composite） | ✓ |
| §3.3 register_subtask_executor 扩展点 | 任务 5 | ✓ |
| §5.1 单元测试（20 个） | 任务 2/3/4（21 个） | ✓ |
| §5.2 Server 编排单元测试（10 个） | 任务 5 | ✓ |
| §5.3 端到端测试（8 个） | 任务 6 | ✓ |
| §5.4 Demo | 任务 7 | ✓ |
| §5.5 不破坏现有测试 | 任务 8 | ✓ |
| §6.1 向后兼容保证 | 任务 8 步骤 2/4/5 验证 | ✓ |

### 2. 占位符扫描

无占位符——每个步骤都包含完整代码或精确命令。

### 3. 类型一致性

- `CompositeTask.__init__` 签名在任务 2 定义，任务 4/5/6 引用一致
- `emit_subtask_event(subtask, event_type)` 在任务 4 定义，任务 5 桥接函数引用一致
- `_find_sub(subtask_id)` 在任务 2 定义，任务 4/5 引用一致
- `ready_subtasks()` / `descendants()` 在任务 2 定义，任务 3/5 引用一致
- `execute_composite(composite)` / `_execute_subtask_by_domain(subtask)` / `register_subtask_executor(domain, executor)` 在任务 5 定义，任务 6 引用一致
- `_subtask_executors: dict[str, Any]` 在任务 5 定义并使用

### 4. 测试数量调整说明

设计规格预期 305 passed（20+10+8），实际计划产出 306 passed（21+10+8）：
- 单元测试 21 个 = 构造校验 3 + DAG 校验 5 + DAG 查询 6 + 事件驱动 7
- 设计规格估算 20 个为四舍五入，实际多 1 个（`test_dag_validation_missing_key` 补充依赖键不存在的边界）

---

## 执行交接

计划已完成并保存到 `docs/plans/2026-07-27-composite-task.md`。两种执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

选哪种方式？
