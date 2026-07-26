"""Deal：交易记录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.core.domain import generate_id


class DealStatus:
    """交易状态枚举。"""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    RESOLVED = "resolved"

    ALL: tuple[str, ...] = (PENDING, ACTIVE, COMPLETED, DISPUTED, CANCELLED, RESOLVED)

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

    def activate(self) -> None:
        """匹配确认后激活。"""
        self._transition(DealStatus.ACTIVE)

    def complete(self) -> None:
        """完成交易。"""
        self._transition(DealStatus.COMPLETED)
        self.completed_at = datetime.utcnow()

    def cancel(self) -> None:
        """取消交易。"""
        if DealStatus.is_terminal(self.status):
            raise RuntimeError(f"交易已处于终态 {self.status}，无法取消")
        self._transition(DealStatus.CANCELLED)

    def open_dispute(self) -> None:
        """开启争议。"""
        if self.status not in (DealStatus.ACTIVE, DealStatus.COMPLETED):
            raise RuntimeError(f"交易状态 {self.status} 不允许开启争议")
        self._transition(DealStatus.DISPUTED)

    def resolve(self, outcome: str = "completed") -> None:
        """解决争议。

        outcome ∈ {"completed", "cancelled"}。
        """
        if self.status != DealStatus.DISPUTED:
            raise RuntimeError(f"交易状态 {self.status} 不允许解决争议")
        self._transition(DealStatus.RESOLVED)
        final = outcome if outcome in (DealStatus.COMPLETED, DealStatus.CANCELLED) else DealStatus.COMPLETED
        self._transition(final)
        if final == DealStatus.COMPLETED:
            self.completed_at = datetime.utcnow()

    def _transition(self, new_status: str) -> None:
        from umcp_core.fsm.deal_fsm import DealStateMachine

        DealStateMachine().validate_transition(self.status, new_status)
        self.status = new_status

    def __repr__(self) -> str:
        return (
            f"<Deal id={self.deal_id} task={self.task_id} "
            f"resource={self.resource_id} status={self.status}>"
        )
