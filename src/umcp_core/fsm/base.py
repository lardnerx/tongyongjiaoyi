"""状态机基础抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


TransitionHandler = Callable[[str, str], None]


class StateMachine(ABC):
    """状态机抽象基类。

    子类需定义 TRANSITIONS：合法状态转移表。
    格式：{from_status: {to_status, to_status, ...}}
    """

    TRANSITIONS: dict[str, set[str]] = {}

    def validate_transition(self, from_status: str, to_status: str) -> None:
        """校验状态转移是否合法，非法时抛出 ValueError。"""
        if from_status == to_status:
            return  # 自状态保持视为合法
        allowed = self.TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ValueError(
                f"非法状态转移: {from_status} → {to_status}。"
                f"合法目标状态: {sorted(allowed) or '<终态>'}"
            )

    def can_transition(self, from_status: str, to_status: str) -> bool:
        """查询状态转移是否合法。"""
        try:
            self.validate_transition(from_status, to_status)
            return True
        except ValueError:
            return False

    @abstractmethod
    def initial_state(self) -> str:
        """返回初始状态。"""
