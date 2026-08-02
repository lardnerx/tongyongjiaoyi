"""任务状态机。"""

from __future__ import annotations

from umcp_core.core.task import TaskStatus
from umcp_core.fsm.base import StateMachine


class TaskStateMachine(StateMachine):
    """任务状态机。

    DRAFT → PUBLISHED → MATCHING → ASSIGNED → IN_PROGRESS → COMPLETED
    任意非终态可 → CANCELLED。
    """

    TRANSITIONS: dict[str, set[str]] = {
        TaskStatus.DRAFT: {TaskStatus.PUBLISHED, TaskStatus.CANCELLED},
        TaskStatus.PUBLISHED: {TaskStatus.MATCHING, TaskStatus.ASSIGNED, TaskStatus.CANCELLED},
        TaskStatus.MATCHING: {TaskStatus.ASSIGNED, TaskStatus.CANCELLED},
        TaskStatus.ASSIGNED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
        TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED, TaskStatus.CANCELLED},
        TaskStatus.COMPLETED: set(),
        TaskStatus.CANCELLED: set(),
    }

    def initial_state(self) -> str:
        return TaskStatus.DRAFT
