"""陪驾教练 router（接单/签到/签退）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.deal import Deal
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

from .orders import apply_check_in, apply_check_out

router = APIRouter(prefix="/api/v1/escort/coaches", tags=["escort-coaches"])


class AcceptDealRequest(BaseModel):
    coach_id: str


class CheckInRequest(BaseModel):
    coach_id: str
    lat: float
    lng: float


class CheckOutRequest(BaseModel):
    coach_id: str
    lat: float
    lng: float


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


@router.post("/deals/{deal_id}/accept", response_model=Envelope)
async def accept_deal(
    deal_id: str,
    req: AcceptDealRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练接单：PENDING → ACTIVE。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.activate()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(_deal_to_info(deal).model_dump())


@router.post("/deals/{deal_id}/check-in", response_model=Envelope)
async def check_in(
    deal_id: str,
    req: CheckInRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签到（按 Deal 维度）：与 /orders/{task_id}/check-in 共用同一实现。

    Task 与 Deal 双向同步，返回 Deal 状态。历史无 Task 的旧交易只推进 Deal。
    """
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    task = server.task_repo.find_by_id(deal.task_id)
    apply_check_in(server, task, deal, req.coach_id, req.lat, req.lng)
    server.event_bus.publish(
        Event(
            type=EventType.CHECK_IN,
            source_layer="ESCORT",
            payload={
                "deal_id": deal_id,
                "coach_id": req.coach_id,
                "lat": req.lat,
                "lng": req.lng,
            },
        )
    )
    return ok(_deal_to_info(deal).model_dump())


@router.post("/deals/{deal_id}/check-out", response_model=Envelope)
async def check_out(
    deal_id: str,
    req: CheckOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签退（按 Deal 维度）：与 /orders/{task_id}/check-out 共用同一实现。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    task = server.task_repo.find_by_id(deal.task_id)
    apply_check_out(server, task, deal)
    server.event_bus.publish(
        Event(
            type=EventType.CHECK_OUT,
            source_layer="ESCORT",
            payload={
                "deal_id": deal_id,
                "coach_id": req.coach_id,
                "lat": req.lat,
                "lng": req.lng,
            },
        )
    )
    return ok(_deal_to_info(deal).model_dump())


class OnlineRequest(BaseModel):
    lat: float
    lng: float


@router.post("/{coach_id}/online", response_model=Envelope)
async def coach_online(
    coach_id: str,
    req: OnlineRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练上线：注册到在线教练集合，并更新位置到 LBS 服务。"""
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        manager.register_online_coach(coach_id)
    # 更新位置到 LBS 服务
    lbs = getattr(server, "lbs_service", None)
    if lbs is not None:
        lbs.update_location(coach_id, req.lat, req.lng)
    return ok({"coach_id": coach_id, "online": True})


@router.post("/{coach_id}/offline", response_model=Envelope)
async def coach_offline(
    coach_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练下线：从在线集合移除。"""
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        manager.unregister_online_coach(coach_id)
    return ok({"coach_id": coach_id, "online": False})
