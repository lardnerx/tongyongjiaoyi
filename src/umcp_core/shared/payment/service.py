"""支付服务：封装网关调用 + 仓储持久化 + 事件发布。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.events.bus import Event, EventBus
from umcp_core.events.types import EventType
from umcp_core.shared.payment.base import (
    PaymentGateway,
    PaymentIntent,
    PaymentStatusEnum,
    PaymentType,
)
from umcp_core.shared.payment.repository import InMemoryPaymentRepository


class PaymentService:
    """支付服务。

    业务流程：
    1. create_payment：调网关创建意图 + 仓储落 PENDING 记录
    2. confirm_payment：网关查询确认已支付 → 更新仓储为 PAID + 发 PAYMENT_PAID 事件
    3. refund：调网关退款 → 更新仓储 + 发 PAYMENT_REFUNDED 事件
    """

    def __init__(
        self,
        gateway: PaymentGateway,
        repo: InMemoryPaymentRepository,
        event_bus: EventBus,
    ) -> None:
        self._gateway = gateway
        self._repo = repo
        self._event_bus = event_bus

    @property
    def repo(self) -> InMemoryPaymentRepository:
        return self._repo

    def create_payment(
        self,
        deal_id: str,
        user_id: str,
        amount: float,
        payment_type: PaymentType,
    ) -> PaymentIntent:
        """创建支付意图并落 PENDING 记录。"""
        intent = self._gateway.create_payment(deal_id, amount, payment_type)
        self._repo.save(
            payment_id=intent.payment_id,
            deal_id=deal_id,
            user_id=user_id,
            amount=amount,
            payment_type=payment_type,
            status=PaymentStatusEnum.PENDING,
            gateway=type(self._gateway).__name__,
        )
        return intent

    def confirm_payment(
        self,
        payment_id: str,
        trade_no: str | None = None,
    ) -> None:
        """确认支付成功：更新状态为 PAID + 发布事件。"""
        self._repo.update_status(
            payment_id=payment_id,
            status=PaymentStatusEnum.PAID,
            trade_no=trade_no,
            paid_at=datetime.utcnow(),
        )
        persisted = self._repo.find_by_id(payment_id)
        self._event_bus.publish(
            Event(
                type=EventType.PAYMENT_PAID,
                source_layer="SHARED",
                payload={
                    "payment_id": payment_id,
                    "deal_id": persisted["deal_id"] if persisted else None,
                    "user_id": persisted["user_id"] if persisted else None,
                    "amount": persisted["amount"] if persisted else None,
                },
            )
        )

    def refund(self, payment_id: str, amount: float, reason: str) -> None:
        """退款：调网关 + 更新仓储 + 发布事件。"""
        result = self._gateway.refund(payment_id, amount, reason)
        if not result.success:
            raise RuntimeError(f"退款失败: {result.message}")
        self._repo.update_status(payment_id, PaymentStatusEnum.REFUNDED)
        persisted = self._repo.find_by_id(payment_id)
        self._event_bus.publish(
            Event(
                type=EventType.PAYMENT_REFUNDED,
                source_layer="SHARED",
                payload={
                    "payment_id": payment_id,
                    "deal_id": persisted["deal_id"] if persisted else None,
                    "refund_amount": amount,
                    "reason": reason,
                },
            )
        )
