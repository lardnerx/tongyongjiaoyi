"""陪驾 Mock 支付 router。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/escort/payments", tags=["escort-payments"])


class MockPayRequest(BaseModel):
    deal_id: str
    payment_type: str = "deposit"  # deposit | balance | full


class PaymentInfo(BaseModel):
    payment_id: str
    deal_id: str
    user_id: str
    amount: float
    payment_type: str
    status: str
    trade_no: str | None = None


@router.post("/mock-pay", response_model=Envelope)
async def mock_pay(
    req: MockPayRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """Mock 支付：创建支付意图 + 同步确认成功。"""
    deal = server.deal_repo.find_by_id(req.deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {req.deal_id} 不存在")

    payment_service = getattr(server, "payment_service", None)
    if payment_service is None:
        raise IllegalStateError(message="支付服务未注册")

    # 计算支付金额（定金 = total * 0.3）
    amount = round((deal.final_amount or 0.0) * 0.3, 2)
    if amount <= 0:
        raise IllegalStateError(message="支付金额必须大于 0")

    payment_type = PaymentType(req.payment_type)
    intent = payment_service.create_payment(
        deal_id=req.deal_id,
        user_id=current_user.user_id,
        amount=amount,
        payment_type=payment_type,
    )
    # Mock 网关同步成功，直接确认
    payment_service.confirm_payment(payment_id=intent.payment_id)

    # 手动发布 PAYMENT_PAID 事件（payload 含 supplier_id 供 WS 推送给教练）
    # 技术债说明：confirm_payment() 内部已发一次 PAYMENT_PAID，但 payload 缺
    # demander_id/supplier_id，WS _extract_user_ids 提取不到推送目标，不会推送。
    # 此处补发一次完整 payload 的事件以驱动 WS 推送。两次发布功能上不冲突
    # （第一次不被推送），后续可改造 PaymentService 让 confirm_payment 从 repo
    # 取完整字段，消除重复发布。
    server.event_bus.publish(
        Event(
            type=EventType.PAYMENT_PAID,
            source_layer="ESCORT",
            payload={
                "payment_id": intent.payment_id,
                "deal_id": req.deal_id,
                "user_id": current_user.user_id,
                "demander_id": deal.demander_id,
                "supplier_id": deal.supplier_id,
                "amount": amount,
            },
        )
    )

    persisted = payment_service.repo.find_by_id(intent.payment_id)
    return ok(
        PaymentInfo(
            payment_id=intent.payment_id,
            deal_id=req.deal_id,
            user_id=current_user.user_id,
            amount=amount,
            payment_type=req.payment_type,
            status=persisted["status"] if persisted else "paid",
            trade_no=persisted.get("trade_no") if persisted else None,
        ).model_dump()
    )


@router.get("/{deal_id}", response_model=Envelope)
async def get_payment_by_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """按 deal_id 查询支付状态（返回最新一条）。"""
    payment_service = getattr(server, "payment_service", None)
    if payment_service is None:
        raise IllegalStateError(message="支付服务未注册")
    records = payment_service.repo.find_by_deal(deal_id)
    if not records:
        raise NotFoundError(message=f"交易 {deal_id} 无支付记录")
    latest = records[-1]
    return ok(
        PaymentInfo(
            payment_id=latest["payment_id"],
            deal_id=latest["deal_id"],
            user_id=latest["user_id"],
            amount=latest["amount"],
            payment_type=latest["type"],
            status=latest["status"],
            trade_no=latest.get("trade_no"),
        ).model_dump()
    )
