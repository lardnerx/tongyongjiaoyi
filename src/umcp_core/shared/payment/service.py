"""支付服务：封装网关调用 + 仓储持久化 + 事件发布。"""
from __future__ import annotations

import logging
import time
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

logger = logging.getLogger(__name__)


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
        _start = time.perf_counter()
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
        logger.info(
            "[CREATE_PAYMENT] done: payment_id=%s deal_id=%s amount=%s gateway=%s elapsed=%.4fs",
            intent.payment_id, deal_id, amount, type(self._gateway).__name__,
            time.perf_counter() - _start,
        )
        return intent

    def confirm_payment(
        self,
        payment_id: str,
        trade_no: str | None = None,
        demander_id: str | None = None,
        supplier_id: str | None = None,
    ) -> None:
        """确认支付成功：更新状态为 PAID + 发布事件。

        Args:
            payment_id: 支付记录 ID
            trade_no: 网关交易号（可选）
            demander_id: 需求方 ID（用于 WS 推送路由）
            supplier_id: 供给方 ID（用于 WS 推送路由）
        """
        _start = time.perf_counter()

        # 查询当前状态快照（仅用于日志记录，不改变业务逻辑）
        before = self._repo.find_by_id(payment_id)
        before_status = before["status"] if before else "N/A"
        before_trade_no = before.get("trade_no", "N/A") if before else "N/A"
        before_gateway = before.get("gateway", "N/A") if before else "N/A"

        logger.info(
            "[CONFIRM_PAYMENT] entry: payment_id=%s trade_no=%s demander_id=%s supplier_id=%s "
            "before_status=%s before_trade_no=%s gateway=%s elapsed=%.4fs",
            payment_id, trade_no, demander_id, supplier_id,
            before_status, before_trade_no, before_gateway,
            time.perf_counter() - _start,
        )

        # 更新状态为 PAID（无论当前状态如何，直接覆盖）
        self._repo.update_status(
            payment_id=payment_id,
            status=PaymentStatusEnum.PAID,
            trade_no=trade_no,
            paid_at=datetime.utcnow(),
        )
        persisted = self._repo.find_by_id(payment_id)
        after_status = persisted["status"] if persisted else "N/A"
        after_trade_no = persisted.get("trade_no", "N/A") if persisted else "N/A"
        after_paid_at = persisted.get("paid_at", "N/A") if persisted else "N/A"
        logger.info(
            "[CONFIRM_PAYMENT] branch=STATUS_UPDATED payment_id=%s before_status=%s after_status=%s "
            "trade_no=%s paid_at=%s elapsed=%.4fs",
            payment_id, before_status, after_status,
            after_trade_no, after_paid_at,
            time.perf_counter() - _start,
        )

        # 发布事件
        event_payload = {
            "payment_id": payment_id,
            "deal_id": persisted["deal_id"] if persisted else None,
            "user_id": persisted["user_id"] if persisted else None,
            "demander_id": demander_id,
            "supplier_id": supplier_id,
            "amount": persisted["amount"] if persisted else None,
        }
        self._event_bus.publish(
            Event(
                type=EventType.PAYMENT_PAID,
                source_layer="SHARED",
                payload=event_payload,
            )
        )
        logger.info(
            "[CONFIRM_PAYMENT] branch=EVENT_PUBLISHED type=PAYMENT_PAID payment_id=%s "
            "deal_id=%s amount=%s event_payload=%s elapsed=%.4fs",
            payment_id, event_payload["deal_id"], event_payload["amount"],
            event_payload, time.perf_counter() - _start,
        )

    def refund(self, payment_id: str, amount: float, reason: str) -> None:
        """退款：调网关 + 更新仓储 + 发布事件。"""
        _start = time.perf_counter()
        before = self._repo.find_by_id(payment_id)
        before_status = before["status"] if before else "N/A"
        before_trade_no = before.get("trade_no", "N/A") if before else "N/A"

        logger.info(
            "[REFUND] entry: payment_id=%s amount=%s reason=%s before_status=%s "
            "before_trade_no=%s elapsed=%.4fs",
            payment_id, amount, reason, before_status, before_trade_no,
            time.perf_counter() - _start,
        )

        # 调用网关退款
        result = self._gateway.refund(payment_id, amount, reason)
        logger.info(
            "[REFUND] branch=GATEWAY_RESULT payment_id=%s success=%s refund_amount=%s message=%s elapsed=%.4fs",
            payment_id, result.success, result.refund_amount, result.message,
            time.perf_counter() - _start,
        )
        if not result.success:
            logger.error(
                "[REFUND] branch=GATEWAY_FAILED payment_id=%s message=%s elapsed=%.4fs",
                payment_id, result.message, time.perf_counter() - _start,
            )
            raise RuntimeError(f"退款失败: {result.message}")

        # 更新状态
        self._repo.update_status(payment_id, PaymentStatusEnum.REFUNDED)
        persisted = self._repo.find_by_id(payment_id)
        logger.info(
            "[REFUND] branch=STATUS_UPDATED payment_id=%s before_status=%s after_status=%s elapsed=%.4fs",
            payment_id, before_status, persisted["status"] if persisted else "N/A",
            time.perf_counter() - _start,
        )

        # 发布事件
        event_payload = {
            "payment_id": payment_id,
            "deal_id": persisted["deal_id"] if persisted else None,
            "refund_amount": amount,
            "reason": reason,
        }
        self._event_bus.publish(
            Event(
                type=EventType.PAYMENT_REFUNDED,
                source_layer="SHARED",
                payload=event_payload,
            )
        )
        logger.info(
            "[REFUND] branch=EVENT_PUBLISHED type=PAYMENT_REFUNDED payment_id=%s "
            "deal_id=%s refund_amount=%s event_payload=%s elapsed=%.4fs",
            payment_id, event_payload["deal_id"], amount,
            event_payload, time.perf_counter() - _start,
        )
