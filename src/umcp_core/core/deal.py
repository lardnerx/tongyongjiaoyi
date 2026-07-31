"""Deal：交易记录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.core.domain import generate_id


class DealStatus:
    """交易状态枚举。"""

    PENDING = "pending"
    ACTIVE = "active"
    IN_SERVICE = "in_service"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    RESOLVED = "resolved"

    ALL: tuple[str, ...] = (PENDING, ACTIVE, IN_SERVICE, COMPLETED, DISPUTED, CANCELLED, RESOLVED)

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        return status in (cls.COMPLETED, cls.CANCELLED)


class Deal:
    """交易记录，关联 Task 与 Resource。

    状态机：PENDING → ACTIVE → COMPLETED
                       ↑         ↓
                   CANCELLED  DISPUTED → RESOLVED → COMPLETED/CANCELLED
    """

    def __init__(
        self,
        task_id: str,
        resource_id: str,
        demander_id: str,
        supplier_id: str,
        deal_id: str | None = None,
        final_amount: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.deal_id: str = deal_id or generate_id("deal")
        self.task_id: str = task_id
        self.resource_id: str = resource_id
        self.demander_id: str = demander_id
        self.supplier_id: str = supplier_id
        self.status: str = DealStatus.PENDING
        self.final_amount: float | None = final_amount
        self.matched_at: datetime = datetime.utcnow()
        self.completed_at: datetime | None = None
        self.metadata: dict[str, Any] = metadata or {}
        self._event_bus = None  # type: ignore[assignment]

    def activate(self) -> None:
        """匹配确认后激活。"""
        self._transition(DealStatus.ACTIVE)
        self._emit(self._get_event_type("DEAL_PAID"))

    def start_service(self) -> None:
        """服务开始（教练签到）。ACTIVE → IN_SERVICE。"""
        self._transition(DealStatus.IN_SERVICE)
        self._emit(self._get_event_type("DEAL_IN_SERVICE"))

    def check_in(self) -> None:
        """签到（start_service 的业务别名）。"""
        self.start_service()

    def complete(self) -> None:
        """完成交易。"""
        self._transition(DealStatus.COMPLETED)
        self.completed_at = datetime.utcnow()
        self._emit(self._get_event_type("DEAL_COMPLETED"))

    def cancel(self) -> None:
        """取消交易。"""
        if DealStatus.is_terminal(self.status):
            raise RuntimeError(f"交易已处于终态 {self.status}，无法取消")
        self._transition(DealStatus.CANCELLED)
        self._emit(self._get_event_type("DEAL_CANCELLED"))

    def open_dispute(self) -> None:
        """开启争议。"""
        if self.status not in (DealStatus.ACTIVE, DealStatus.COMPLETED):
            raise RuntimeError(f"交易状态 {self.status} 不允许开启争议")
        self._transition(DealStatus.DISPUTED)
        self._emit(self._get_event_type("DEAL_DISPUTED"))

    def resolve(self, outcome: str = "completed") -> None:
        """解决争议。

        outcome ∈ {"completed", "cancelled"}。
        """
        if self.status != DealStatus.DISPUTED:
            raise RuntimeError(f"交易状态 {self.status} 不允许解决争议")
        self._transition(DealStatus.RESOLVED)
        self._emit(self._get_event_type("DEAL_RESOLVED"))
        final = outcome if outcome in (DealStatus.COMPLETED, DealStatus.CANCELLED) else DealStatus.COMPLETED
        self._transition(final)
        if final == DealStatus.COMPLETED:
            self.completed_at = datetime.utcnow()

    def _transition(self, new_status: str) -> None:
        from umcp_core.fsm.deal_fsm import DealStateMachine

        DealStateMachine().validate_transition(self.status, new_status)
        self.status = new_status

    def bind_event_bus(self, bus: "EventBus") -> None:
        """绑定事件总线。"""
        self._event_bus = bus

    def _get_event_type(self, name: str):
        """延迟导入 EventType，避免循环依赖。"""
        from umcp_core.events.types import EventType
        return getattr(EventType, name)

    def _emit(self, event_type, payload: dict[str, Any] | None = None) -> None:
        """发布事件。未绑定 event_bus 时静默返回。"""
        if self._event_bus is None:
            return
        from umcp_core.events.bus import Event

        self._event_bus.publish(
            Event(
                type=event_type,
                source_layer="L4",
                payload={
                    "deal_id": self.deal_id,
                    "task_id": self.task_id,
                    "demander_id": self.demander_id,
                    "supplier_id": self.supplier_id,
                    **(payload or {}),
                },
            )
        )

    def __repr__(self) -> str:
        return (
            f"<Deal id={self.deal_id} task={self.task_id} "
            f"resource={self.resource_id} status={self.status}>"
        )
