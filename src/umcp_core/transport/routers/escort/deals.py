"""陪驾预约单教练确认/拒绝 router。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.deal import DealStatus
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError, PermissionDeniedError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/escort/deals", tags=["escort-deals"])


class ConfirmRequest(BaseModel):
    coach_id: str


class RejectRequest(BaseModel):
    coach_id: str
    reason: str = ""


class DealStatusInfo(BaseModel):
    deal_id: str
    status: str
    task_id: str


@router.post("/{deal_id}/confirm", response_model=Envelope)
async def confirm_deal(
    deal_id: str,
    req: ConfirmRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练确认预约单：deal pending → active。"""
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能确认自己的订单")

    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    if deal.supplier_id != req.coach_id:
        raise PermissionDeniedError(message="只有该订单的教练才能确认")
    if deal.status != DealStatus.PENDING:
        raise IllegalStateError(message=f"交易状态 {deal.status} 不允许确认")

    deal.bind_event_bus(server.event_bus)
    try:
        deal.activate()  # pending → active，发 DEAL_PAID 事件
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)

    return ok(
        DealStatusInfo(
            deal_id=deal.deal_id,
            status=deal.status,
            task_id=deal.task_id,
        ).model_dump()
    )


@router.post("/{deal_id}/reject", response_model=Envelope)
async def reject_deal(
    deal_id: str,
    req: RejectRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练拒绝预约单：deal pending → cancelled + 退款。"""
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能拒绝自己的订单")

    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    if deal.supplier_id != req.coach_id:
        raise PermissionDeniedError(message="只有该订单的教练才能拒绝")
    if deal.status != DealStatus.PENDING:
        raise IllegalStateError(message=f"交易状态 {deal.status} 不允许拒绝")

    deal.bind_event_bus(server.event_bus)
    try:
        deal.cancel()  # pending → cancelled，发 DEAL_CANCELLED 事件
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)

    # 退款（如果已有支付记录）
    payment_service = getattr(server, "payment_service", None)
    if payment_service is not None:
        records = payment_service.repo.find_by_deal(deal_id)
        for record in records:
            if record["status"] == "paid":
                payment_service.refund(
                    payment_id=record["payment_id"],
                    amount=record["amount"],
                    reason=req.reason or "教练拒绝预约单",
                )

    # 同步取消 task
    task = server.task_repo.find_by_id(deal.task_id)
    if task is not None and task.status != "cancelled":
        try:
            task.cancel()
            server.task_repo.save(task)
        except (RuntimeError, ValueError):
            pass  # task 可能已终态，忽略

    return ok(
        DealStatusInfo(
            deal_id=deal.deal_id,
            status=deal.status,
            task_id=deal.task_id,
        ).model_dump()
    )
