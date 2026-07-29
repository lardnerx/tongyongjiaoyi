"""事件类型定义。"""

from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    """标准事件类型。

    所有层通过事件总线解耦，L6 的异常检测、L7 的规则审计都通过订阅事件实现。
    """

    # 任务生命周期
    TASK_PUBLISHED = "task.published"
    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    TASK_CANCELLED = "task.cancelled"

    # 匹配
    MATCH_PROPOSED = "match.proposed"
    MATCH_ACCEPTED = "match.accepted"
    MATCH_REJECTED = "match.rejected"

    # 支付
    PAYMENT_HELD = "payment.held"
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_REFUNDED = "payment.refunded"

    # 信任
    EVALUATION_SUBMITTED = "evaluation.submitted"
    TRUST_UPDATED = "trust.updated"

    # 治理与异常
    ANOMALY_DETECTED = "anomaly.detected"
    RULE_TRIGGERED = "rule.triggered"
    DISPUTE_OPENED = "dispute.opened"
    DISPUTE_RESOLVED = "dispute.resolved"

    # 资源生命周期（阶段五B 扩展）
    RESOURCE_REGISTERED = "resource.registered"
    RESOURCE_STATUS_CHANGED = "resource.status_changed"

    # 交易生命周期（阶段五B 扩展）
    DEAL_CREATED = "deal.created"
    DEAL_PAID = "deal.paid"
    DEAL_COMPLETED = "deal.completed"
    DEAL_DISPUTED = "deal.disputed"

    # 复合任务编排（阶段四C）
    SUBTASK_COMPLETED = "subtask.completed"
    SUBTASK_CANCELLED = "subtask.cancelled"
    COMPOSITE_COMPLETED = "composite.completed"
    COMPOSITE_FAILED = "composite.failed"
