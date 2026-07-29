"""交易路由。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.deal import Deal
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
    server.deal_repo.save(deal)
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
    all_deals = list(getattr(server.deal_repo, "_deals", {}).values())
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
    try:
        deal.activate()
    except RuntimeError as e:
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
    try:
        deal.complete()
    except RuntimeError as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="已完成")


@router.post("/{deal_id}/dispute", response_model=Envelope)
async def dispute_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """发起争议。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    try:
        deal.open_dispute()
    except RuntimeError as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="争议已开启")
