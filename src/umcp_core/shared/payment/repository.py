"""支付记录仓储。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base
from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType


class PaymentModel(Base):
    """支付记录表。"""

    __tablename__ = "payments"

    payment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    gateway: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InMemoryPaymentRepository:
    """内存支付仓储（开发与测试用）。"""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def save(
        self,
        payment_id: str,
        deal_id: str,
        user_id: str,
        amount: float,
        payment_type: PaymentType,
        status: PaymentStatusEnum,
        gateway: str,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._items[payment_id] = {
            "payment_id": payment_id,
            "deal_id": deal_id,
            "user_id": user_id,
            "amount": amount,
            "type": payment_type.value if isinstance(payment_type, PaymentType) else str(payment_type),
            "status": status.value if isinstance(status, PaymentStatusEnum) else str(status),
            "gateway": gateway,
            "trade_no": trade_no,
            "paid_at": paid_at,
            "refunded_at": None,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        }

    def find_by_id(self, payment_id: str) -> dict[str, Any] | None:
        item = self._items.get(payment_id)
        return dict(item) if item else None

    def find_by_deal(self, deal_id: str) -> list[dict[str, Any]]:
        return [dict(v) for v in self._items.values() if v["deal_id"] == deal_id]

    def find_by_status(self, status: PaymentStatusEnum) -> list[dict[str, Any]]:
        """按支付状态查询记录。"""
        target = status.value if isinstance(status, PaymentStatusEnum) else str(status)
        return [dict(v) for v in self._items.values() if v["status"] == target]

    def update_status(
        self,
        payment_id: str,
        status: PaymentStatusEnum,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
    ) -> None:
        if payment_id in self._items:
            self._items[payment_id]["status"] = status.value
            if status is PaymentStatusEnum.REFUNDED:
                self._items[payment_id]["refunded_at"] = datetime.utcnow()
            if trade_no:
                self._items[payment_id]["trade_no"] = trade_no
            if paid_at:
                self._items[payment_id]["paid_at"] = paid_at


class PostgresPaymentRepository:
    """PG 支付仓储。"""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def save(
        self,
        payment_id: str,
        deal_id: str,
        user_id: str,
        amount: float,
        payment_type: PaymentType,
        status: PaymentStatusEnum,
        gateway: str,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        with self._session_factory() as session:
            m = PaymentModel(
                payment_id=payment_id,
                deal_id=deal_id,
                user_id=user_id,
                amount=amount,
                type=payment_type.value if isinstance(payment_type, PaymentType) else str(payment_type),
                status=status.value if isinstance(status, PaymentStatusEnum) else str(status),
                gateway=gateway,
                trade_no=trade_no,
                paid_at=paid_at,
                metadata_=metadata,
                created_at=datetime.utcnow(),
            )
            session.add(m)
            session.commit()

    def find_by_id(self, payment_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            m = session.get(PaymentModel, payment_id)
            return self._to_dict(m) if m else None

    def find_by_deal(self, deal_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.query(PaymentModel).filter_by(deal_id=deal_id).all()
            return [self._to_dict(m) for m in rows]

    def find_by_status(self, status: PaymentStatusEnum) -> list[dict[str, Any]]:
        """按支付状态查询记录。"""
        target = status.value if isinstance(status, PaymentStatusEnum) else str(status)
        with self._session_factory() as session:
            rows = session.query(PaymentModel).filter_by(status=target).all()
            return [self._to_dict(m) for m in rows]

    def update_status(
        self,
        payment_id: str,
        status: PaymentStatusEnum,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
    ) -> None:
        with self._session_factory() as session:
            m = session.get(PaymentModel, payment_id)
            if m is None:
                return
            target = status.value if isinstance(status, PaymentStatusEnum) else str(status)
            m.status = target
            if target == PaymentStatusEnum.REFUNDED.value:
                m.refunded_at = datetime.utcnow()
            if trade_no:
                m.trade_no = trade_no
            if paid_at:
                m.paid_at = paid_at
            session.commit()

    @staticmethod
    def _to_dict(m: PaymentModel) -> dict[str, Any]:
        return {
            "payment_id": m.payment_id,
            "deal_id": m.deal_id,
            "user_id": m.user_id,
            "amount": float(m.amount),
            "type": m.type,
            "status": m.status,
            "gateway": m.gateway,
            "trade_no": m.trade_no,
            "paid_at": m.paid_at,
            "refunded_at": m.refunded_at,
            "metadata": m.metadata_ or {},
            "created_at": m.created_at,
        }
