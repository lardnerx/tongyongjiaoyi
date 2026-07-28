"""CompositeTask：跨 domain 复合任务（DAG 编排）。"""

from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import CustomTask, PackageTask, StandardTask, Task, TaskStatus
from umcp_core.events.bus import Event, EventBus
from umcp_core.events.types import EventType


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

    def find_subtask(self, task_id: str) -> Task:
        """查找指定 ID 的子任务（公共接口，供外部调用）。"""
        return self._find_sub(task_id)

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

    # ---- 事件订阅与状态转移 ----

    def bind_event_bus(self, bus: EventBus) -> None:
        """绑定事件总线并订阅子任务事件。"""
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
        # 任一子任务被取消 → 父任务立即失败（无需等待所有子任务终态化）
        if any(s.status == TaskStatus.CANCELLED for s in self.subtasks):
            self._fail_composite()
            return
        if any(not TaskStatus.is_terminal(s.status) for s in self.subtasks):
            return
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
        # CompositeTask 由事件驱动保证一致性，直接设置终态
        # （跳过 PackageTask.complete 的子任务校验和状态机 DRAFT→COMPLETED 校验）
        self.status = TaskStatus.COMPLETED
        from datetime import datetime

        self.updated_at = datetime.utcnow()
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
