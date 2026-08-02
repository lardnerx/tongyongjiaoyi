"""Task 抽象：标准化任务、非标准化任务、混合任务。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from umcp_core.core.domain import Attachment, DomainTag, SpatioTemporalConstraint, generate_id
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType


class TaskStatus:
    """任务状态枚举（字符串常量，便于序列化与跨语言互通）。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    MATCHING = "matching"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    ALL: tuple[str, ...] = (
        DRAFT,
        PUBLISHED,
        MATCHING,
        ASSIGNED,
        IN_PROGRESS,
        COMPLETED,
        CANCELLED,
    )

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        return status in (cls.COMPLETED, cls.CANCELLED)


class Task(ABC):
    """任务根抽象基类。

    生命周期状态机：DRAFT → PUBLISHED → MATCHING → ASSIGNED → IN_PROGRESS → COMPLETED
    任意非终态可 → CANCELLED。
    """

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        task_id: str | None = None,
        title: str = "",
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.task_id: str = task_id or generate_id("task")
        self.demander_id: str = demander_id
        self.domain_tag: DomainTag = domain_tag
        self.title: str = title
        self.description: str = description
        self.status: str = TaskStatus.DRAFT
        self.domain_tags: list[DomainTag] = [domain_tag]
        self.attachments: list[Attachment] = []
        self.custom_fields: dict[str, Any] = metadata or {}
        self.created_at: datetime = datetime.utcnow()
        self.updated_at: datetime = datetime.utcnow()
        self.assigned_resource_id: str | None = None
        self._event_bus: EventBus | None = None

    def bind_event_bus(self, bus: EventBus) -> None:
        """绑定事件总线，用于状态变更时发布事件。"""
        self._event_bus = bus

    def is_event_bus_bound(self) -> bool:
        """返回事件总线是否已绑定。"""
        return self._event_bus is not None

    @abstractmethod
    def task_type(self) -> str:
        """返回任务类型标识，如 'standard'、'custom'、'package'。"""

    def publish(self) -> None:
        """发布任务，进入 MATCHING 阶段。"""
        self._transition(TaskStatus.PUBLISHED)
        self._transition(TaskStatus.MATCHING)
        self._emit(EventType.TASK_PUBLISHED)

    def publish_for_claim(self) -> None:
        """发布任务但不进入 MATCHING 状态（抢单模式专用）。

        与 publish() 不同，只过渡到 PUBLISHED 状态，
        等待教练主动抢单（claim）后才进入 ASSIGNED。
        """
        self._transition(TaskStatus.PUBLISHED)
        self._emit(EventType.TASK_PUBLISHED)

    def cancel(self) -> None:
        """取消任务。"""
        if TaskStatus.is_terminal(self.status):
            raise RuntimeError(f"任务已处于终态 {self.status}，无法取消")
        self._transition(TaskStatus.CANCELLED)
        self._emit(EventType.TASK_COMPLETED, payload={"cancelled": True})

    def complete(self) -> None:
        """完成任务。"""
        self._transition(TaskStatus.COMPLETED)
        self._emit(EventType.TASK_COMPLETED)

    def assign_to(self, resource_id: str) -> None:
        """将任务指派给某个资源。"""
        if self.status not in (TaskStatus.MATCHING, TaskStatus.PUBLISHED):
            raise RuntimeError(f"任务状态 {self.status} 不允许指派")
        self.assigned_resource_id = resource_id
        self._transition(TaskStatus.ASSIGNED)
        self._emit(
            EventType.TASK_ASSIGNED,
            payload={"supplier_id": resource_id},
        )

    def start_execution(self) -> None:
        """开始执行。"""
        self._transition(TaskStatus.IN_PROGRESS)

    def _transition(self, new_status: str) -> None:
        from umcp_core.fsm.task_fsm import TaskStateMachine

        TaskStateMachine().validate_transition(self.status, new_status)
        self.status = new_status
        self.updated_at = datetime.utcnow()

    def _emit(self, event_type: EventType, payload: dict[str, Any] | None = None) -> None:
        if self._event_bus is None:
            return
        from umcp_core.events.bus import Event

        self._event_bus.publish(
            Event(
                type=event_type,
                source_layer="L2",
                payload={
                    "task_id": self.task_id,
                    "demander_id": self.demander_id,
                    **(payload or {}),
                },
            )
        )

    def add_attachment(self, attachment: Attachment) -> None:
        self.attachments.append(attachment)

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id={self.task_id} "
            f"domain={self.domain_tag} status={self.status}>"
        )


class StandardTask(Task):
    """标准化任务：可自动匹配、自动定价。

    时空标签可选（出行有起终点，设计/咨询无地点）。
    """

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        spatio_temporal: SpatioTemporalConstraint | None = None,
        structured_fields: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(demander_id, domain_tag, **kwargs)
        self.spatio_temporal: SpatioTemporalConstraint | None = spatio_temporal
        self.structured_fields: dict[str, Any] = structured_fields or {}

    def task_type(self) -> str:
        return "standard"


class CustomTask(Task):
    """非标准化任务：需沟通、报价、选标。"""

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        budget_min: float | None = None,
        budget_max: float | None = None,
        proposal_requirements: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(demander_id, domain_tag, **kwargs)
        self.budget_min: float | None = budget_min
        self.budget_max: float | None = budget_max
        self.proposal_requirements: list[str] = proposal_requirements or []
        self.proposals: list[dict[str, Any]] = []

    def task_type(self) -> str:
        return "custom"

    def submit_proposal(self, supplier_id: str, amount: float, proposal: dict[str, Any]) -> None:
        """供给方提交报价方案。"""
        self.proposals.append(
            {"supplier_id": supplier_id, "amount": amount, "proposal": proposal}
        )


class PackageTask(Task):
    """混合任务：包含标准子任务与非标协调任务。"""

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        standard_sub_tasks: list[StandardTask] | None = None,
        custom_sub_task: CustomTask | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(demander_id, domain_tag, **kwargs)
        self.standard_sub_tasks: list[StandardTask] = standard_sub_tasks or []
        self.custom_sub_task: CustomTask | None = custom_sub_task

    def task_type(self) -> str:
        return "package"
