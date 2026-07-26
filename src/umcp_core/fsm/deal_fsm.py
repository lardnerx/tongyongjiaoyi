"""交易状态机。"""

from __future__ import annotations

from umcp_core.core.deal import DealStatus
from umcp_core.fsm.base import StateMachine


class DealStateMachine(StateMachine):
    """交易状态机。

    PENDING → ACTIVE → COMPLETED
                 ↑         ↓
             CANCELLED  DISPUTED → RESOLVED → COMPLETED/CANCELLED
    """

    TRANSITIONS: dict[str, set[str]] = {
        DealStatus.PENDING: {DealStatus.ACTIVE, DealStatus.CANCELLED},
        DealStatus.ACTIVE: {DealStatus.COMPLETED, DealStatus.DISPUTED, DealStatus.CANCELLED},
        DealStatus.DISPUTED: {DealStatus.RESOLVED},
        DealStatus.RESOLVED: {DealStatus.COMPLETED, DealStatus.CANCELLED},
        DealStatus.COMPLETED: set(),
        DealStatus.CANCELLED: set(),
    }

    def initial_state(self) -> str:
        return DealStatus.PENDING
