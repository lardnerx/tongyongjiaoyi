"""测试状态机：TaskStateMachine 与 DealStateMachine。"""

from __future__ import annotations

import pytest

from umcp_core.core.deal import DealStatus
from umcp_core.core.task import TaskStatus
from umcp_core.fsm import DealStateMachine, TaskStateMachine


class TestTaskStateMachine:
    def test_initial_state(self):
        fsm = TaskStateMachine()
        assert fsm.initial_state() == TaskStatus.DRAFT

    def test_valid_transitions(self):
        fsm = TaskStateMachine()
        # 完整正常流程
        fsm.validate_transition(TaskStatus.DRAFT, TaskStatus.PUBLISHED)
        fsm.validate_transition(TaskStatus.PUBLISHED, TaskStatus.MATCHING)
        fsm.validate_transition(TaskStatus.MATCHING, TaskStatus.ASSIGNED)
        fsm.validate_transition(TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS)
        fsm.validate_transition(TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED)

    def test_cancel_from_any_non_terminal(self):
        fsm = TaskStateMachine()
        for state in [
            TaskStatus.DRAFT,
            TaskStatus.PUBLISHED,
            TaskStatus.MATCHING,
            TaskStatus.ASSIGNED,
            TaskStatus.IN_PROGRESS,
        ]:
            assert fsm.can_transition(state, TaskStatus.CANCELLED)

    def test_invalid_skip_transition(self):
        fsm = TaskStateMachine()
        assert not fsm.can_transition(TaskStatus.DRAFT, TaskStatus.COMPLETED)
        assert not fsm.can_transition(TaskStatus.DRAFT, TaskStatus.IN_PROGRESS)

    def test_terminal_no_outgoing(self):
        fsm = TaskStateMachine()
        assert not fsm.can_transition(TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS)
        assert not fsm.can_transition(TaskStatus.CANCELLED, TaskStatus.PUBLISHED)

    def test_same_state_allowed(self):
        fsm = TaskStateMachine()
        # 自状态保持视为合法
        fsm.validate_transition(TaskStatus.MATCHING, TaskStatus.MATCHING)

    def test_invalid_transition_raises_with_help(self):
        fsm = TaskStateMachine()
        with pytest.raises(ValueError, match="非法状态转移"):
            fsm.validate_transition(TaskStatus.DRAFT, TaskStatus.COMPLETED)


class TestDealStateMachine:
    def test_initial_state(self):
        fsm = DealStateMachine()
        assert fsm.initial_state() == DealStatus.PENDING

    def test_normal_flow(self):
        fsm = DealStateMachine()
        fsm.validate_transition(DealStatus.PENDING, DealStatus.ACTIVE)
        fsm.validate_transition(DealStatus.ACTIVE, DealStatus.COMPLETED)

    def test_dispute_flow(self):
        fsm = DealStateMachine()
        fsm.validate_transition(DealStatus.ACTIVE, DealStatus.DISPUTED)
        fsm.validate_transition(DealStatus.DISPUTED, DealStatus.RESOLVED)
        fsm.validate_transition(DealStatus.RESOLVED, DealStatus.COMPLETED)
        fsm.validate_transition(DealStatus.RESOLVED, DealStatus.CANCELLED)

    def test_invalid_skip(self):
        fsm = DealStateMachine()
        assert not fsm.can_transition(DealStatus.PENDING, DealStatus.COMPLETED)
        assert not fsm.can_transition(DealStatus.PENDING, DealStatus.DISPUTED)

    def test_cancel_from_pending_or_active(self):
        fsm = DealStateMachine()
        assert fsm.can_transition(DealStatus.PENDING, DealStatus.CANCELLED)
        assert fsm.can_transition(DealStatus.ACTIVE, DealStatus.CANCELLED)
