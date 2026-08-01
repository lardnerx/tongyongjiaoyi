"""Mock 支付网关（开发与测试用，同步成功）。"""
from __future__ import annotations

import uuid
from datetime import datetime

from umcp_core.shared.payment.base import (
    PaymentGateway,
    PaymentIntent,
    PaymentStatus,
    PaymentStatusEnum,
    PaymentType,
    RefundResult,
)


class MockGateway(PaymentGateway):
    """Mock 网关：所有操作同步成功，用于开发联调。"""

    def __init__(self) -> None:
        self._payments: dict[str, PaymentIntent] = {}
        self._trade_nos: dict[str, str] = {}

    def create_payment(
        self, deal_id: str, amount: float, payment_type: PaymentType
    ) -> PaymentIntent:
        payment_id = f"pay_mock_{uuid.uuid4().hex[:12]}"
        intent = PaymentIntent(
            payment_id=payment_id,
            deal_id=deal_id,
            amount=amount,
            payment_type=payment_type,
            client_secret=f"mock_secret_{payment_id}",
        )
        self._payments[payment_id] = intent
        self._trade_nos[payment_id] = f"mock_trade_{payment_id}"
        return intent

    def query_payment(self, payment_id: str) -> PaymentStatus:
        if payment_id not in self._payments:
            return PaymentStatus(
                payment_id=payment_id,
                status=PaymentStatusEnum.FAILED,
                trade_no="",
            )
        return PaymentStatus(
            payment_id=payment_id,
            status=PaymentStatusEnum.PAID,
            trade_no=self._trade_nos[payment_id],
            paid_at=datetime.utcnow(),
        )

    def refund(self, payment_id: str, amount: float, reason: str) -> RefundResult:
        if payment_id not in self._payments:
            return RefundResult(
                payment_id=payment_id,
                success=False,
                refund_amount=0.0,
                message="支付单不存在",
            )
        return RefundResult(
            payment_id=payment_id,
            success=True,
            refund_amount=amount,
            trade_no=self._trade_nos[payment_id],
            message="mock refund ok",
        )

    def handle_callback(self, raw_data: bytes) -> dict:
        return {"status": "paid", "raw": raw_data.decode("utf-8", errors="ignore")}
