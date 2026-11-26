"""交易路由。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.deal import Deal
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, PaginatedData, ok, paginated

router = APIRouter()


class CreateDealRequest(BaseModel):
    task_id: str
    resource_id: str
    demander_id: str
    supplier_id: str
    final_amount: float | None = None


class ResolveDealRequest(BaseModel):
    outcome: str = "completed"


class DisputeDealRequest(BaseModel):
    reason: str = ""
    evidence: dict[str, Any] = {}


class ArbitrationInfo(BaseModel):
    dispute_id: str
    outcome: str
    refund_amount: float = 0.0
    penalty: float = 0.0
    reason: str = ""
    deal_status: str


class DealInfo(BaseModel):
    deal_id: str
    task_id: str
    resource_id: str
    demander_id: str
    supplier_id: str
    status: str
    final_amount: float | None = None


def _deal_to_info(deal: Deal) -> DealInfo:
    return DealInfo(
        deal_id=deal.deal_id,
        task_id=deal.task_id,
        resource_id=deal.resource_id,
        demander_id=deal.demander_id,
        supplier_id=deal.supplier_id,
        status=deal.status,
        final_amount=deal.final_amount,
    )


@router.post("", response_model=Envelope[DealInfo])
async def create_deal(
    req: CreateDealRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[DealInfo]:
    """创建交易。"""
    deal = Deal(
        task_id=req.task_id,
        resource_id=req.resource_id,
        demander_id=req.demander_id,
        supplier_id=req.supplier_id,
        final_amount=req.final_amount,
    )
    deal.bind_event_bus(server.event_bus)
    server.deal_repo.save(deal)
    # 发布 DEAL_CREATED 事件（构造时无 event_bus，由 router 显式发布）
    server.event_bus.publish(
        Event(
            type=EventType.DEAL_CREATED,
            source_layer="L4",
            payload={
                "deal_id": deal.deal_id,
                "task_id": deal.task_id,
                "resource_id": deal.resource_id,
                "demander_id": deal.demander_id,
                "supplier_id": deal.supplier_id,
            },
        )
    )
    return ok(_deal_to_info(deal))


@router.get("", response_model=Envelope[PaginatedData[DealInfo]])
async def list_deals(
    task_id: str | None = None,
    supplier_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[DealInfo]]:
    """查询交易列表。"""
    all_deals = server.deal_repo.list_all()
    if task_id:
        all_deals = [d for d in all_deals if d.task_id == task_id]
    if supplier_id:
        all_deals = [d for d in all_deals if d.supplier_id == supplier_id]
    if status:
        all_deals = [d for d in all_deals if d.status == status]

    total = len(all_deals)
    start = (page - 1) * size
    end = start + size
    page_items = all_deals[start:end]
    return paginated(
        items=[_deal_to_info(d) for d in page_items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{deal_id}", response_model=Envelope[DealInfo])
async def get_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[DealInfo]:
    """查询交易详情。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    return ok(_deal_to_info(deal))


@router.post("/{deal_id}/activate", response_model=Envelope)
async def activate_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """激活交易。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.activate()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="已激活")


@router.post("/{deal_id}/complete", response_model=Envelope)
async def complete_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """完成交易。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.complete()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="已完成")


def _build_dispute(
    deal: Deal, initiator: User, req: DisputeDealRequest | None
) -> "Dispute":
    """由交易与请求构造 L7 争议记录。"""
    from umcp_core.core.domain import generate_id
    from umcp_core.layers.l7 import Dispute

    respondent_id = (
        deal.supplier_id
        if initiator.user_id == deal.demander_id
        else deal.demander_id
    )
    return Dispute(
        dispute_id=generate_id("dispute"),
        deal_id=deal.deal_id,
        initiator_id=initiator.user_id,
        respondent_id=respondent_id,
        reason=req.reason if req else "",
        evidence=dict(req.evidence or {}) if req else {},
    )


def _arbitration_info(result: Any, deal_status: str) -> ArbitrationInfo:
    return ArbitrationInfo(
        dispute_id=result.dispute_id,
        outcome=result.outcome,
        refund_amount=result.refund_amount,
        penalty=result.penalty,
        reason=result.reason,
        deal_status=deal_status,
    )


@router.post("/{deal_id}/dispute", response_model=Envelope[ArbitrationInfo])
async def dispute_deal(
    deal_id: str,
    req: DisputeDealRequest | None = None,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[ArbitrationInfo]:
    """发起争议，并调用 L7 仲裁策略生成裁决建议（不自动执行）。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.open_dispute()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e

    dispute = _build_dispute(deal, current_user, req)
    proposal = server.rule_engine.arbitrate(dispute)
    deal.metadata["dispute"] = {
        "dispute_id": dispute.dispute_id,
        "initiator_id": dispute.initiator_id,
        "respondent_id": dispute.respondent_id,
        "reason": dispute.reason,
        "evidence": dispute.evidence,
        "status": dispute.status,
        "arbitration": {
            "outcome": proposal.outcome,
            "refund_amount": proposal.refund_amount,
            "penalty": proposal.penalty,
            "reason": proposal.reason,
        },
    }
    server.deal_repo.save(deal)
    return ok(_arbitration_info(proposal, deal.status), message="争议已开启")


@router.post("/{deal_id}/arbitrate", response_model=Envelope[ArbitrationInfo])
async def arbitrate_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[ArbitrationInfo]:
    """执行 L7 仲裁并落定交易状态。"""
    from umcp_core.layers.l7 import Dispute

    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    if deal.status != "disputed":
        raise IllegalStateError(message=f"交易状态 {deal.status} 不在争议中，无法仲裁")

    stored = deal.metadata.get("dispute") or {}
    dispute = Dispute(
        dispute_id=stored.get("dispute_id", ""),
        deal_id=deal.deal_id,
        initiator_id=stored.get("initiator_id", current_user.user_id),
        respondent_id=stored.get("respondent_id", ""),
        reason=stored.get("reason", ""),
        evidence=stored.get("evidence", {}) or {},
    )
    result = server.rule_engine.arbitrate(dispute)

    deal.bind_event_bus(server.event_bus)
    try:
        deal.resolve(outcome=result.outcome)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e

    dispute.status = "resolved"
    stored.update(
        status="resolved",
        arbitration={
            "outcome": result.outcome,
            "refund_amount": result.refund_amount,
            "penalty": result.penalty,
            "reason": result.reason,
        },
    )
    server.deal_repo.save(deal)
    return ok(_arbitration_info(result, deal.status), message="仲裁已完成")


@router.post("/{deal_id}/cancel", response_model=Envelope)
async def cancel_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """取消交易。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.cancel()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="已取消")


@router.post("/{deal_id}/resolve", response_model=Envelope)
async def resolve_deal(
    deal_id: str,
    req: ResolveDealRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """解决争议。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.resolve(outcome=req.outcome)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="争议已解决")
