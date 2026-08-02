"""陪驾订单 router（学员下单/取消/查询）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import TaskStatus
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok
from plugins.escort_driving.tasks import EscortTask

router = APIRouter(prefix="/api/v1/escort", tags=["escort-orders"])


class CreateOrderRequest(BaseModel):
    """下单请求。"""

    demander_id: str
    domain_tag: str
    origin_lat: float
    origin_lng: float
    car_type: str
    required_skills: list[str]
    duration_hours: int
    order_type: str = "REALTIME"
    scheduled_at: str | None = None
    coach_level_pref: str = "ANY"
    title: str | None = None
    description: str | None = None


class OrderInfo(BaseModel):
    """订单信息（实时单）。"""

    task_id: str
    order_type: str
    status: str
    demander_id: str
    car_type: str
    duration_hours: int
    assigned_resource_id: str | None = None
    title: str | None = None


class ScheduledOrderInfo(BaseModel):
    """预约单信息（含候选教练）。"""

    task_id: str
    order_type: str
    candidates: list[str]


def _task_to_order_info(task: EscortTask) -> OrderInfo:
    return OrderInfo(
        task_id=task.task_id,
        order_type=task.order_type,
        status=task.status,
        demander_id=task.demander_id,
        car_type=task.structured_fields.get("car_type", ""),
        duration_hours=task.structured_fields.get("duration_hours", 0),
        assigned_resource_id=task.assigned_resource_id,
        title=task.title,
    )


@router.post("/orders", response_model=Envelope)
async def create_order(
    req: CreateOrderRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """学员下单（实时单/预约单）。"""
    scheduled_at = None
    if req.scheduled_at:
        scheduled_at = datetime.fromisoformat(req.scheduled_at)
    task = EscortTask(
        demander_id=req.demander_id,
        domain_tag=DomainTag.of(req.domain_tag),
        origin_lat=req.origin_lat,
        origin_lng=req.origin_lng,
        car_type=req.car_type,
        required_skills=req.required_skills,
        duration_hours=req.duration_hours,
        order_type=req.order_type,
        scheduled_at=scheduled_at,
        coach_level_pref=req.coach_level_pref,
    )
    task.title = req.title
    task.description = req.description

    if req.order_type == "SCHEDULED":
        # 预约单：调 ScheduledMatchStrategy 返回 Top3，不自动 publish
        strategy = server.scheduled_match_strategy_for(req.domain_tag)
        if strategy is None:
            raise IllegalStateError(
                message=f"domain {req.domain_tag} 未注册预约单匹配策略"
            )
        candidates = server.resource_repo.list_all()
        domain_candidates = [
            r for r in candidates if r.domain_tag.value == req.domain_tag
        ]
        result = strategy.execute(task, domain_candidates)
        # 保存任务为 DRAFT 状态（等待学员选择教练后再 publish）
        server.task_repo.save(task)
        return ok(
            data=ScheduledOrderInfo(
                task_id=task.task_id,
                order_type="SCHEDULED",
                candidates=result.candidates,
            ).model_dump()
        )

    # 实时单：只 publish，等待教练抢单（抢单模式）
    try:
        server.task_repo.save(task)
        task.bind_event_bus(server.event_bus)
        # 抢单模式：只过渡到 PUBLISHED（不进入 MATCHING），发 TASK_PUBLISHED 事件
        # task.publish() 会继续推进到 MATCHING（自动匹配语义），与抢单模式不符
        task._transition(TaskStatus.PUBLISHED)
        task._emit(EventType.TASK_PUBLISHED)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 广播给所有在线教练
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        import asyncio
        message = {
            "type": "task.published",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "task_id": task.task_id,
                "demander_id": task.demander_id,
                "origin_lat": req.origin_lat,
                "origin_lng": req.origin_lng,
                "car_type": req.car_type,
                "duration_hours": req.duration_hours,
                "coach_level_pref": req.coach_level_pref,
            },
        }
        try:
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_online_coaches(message), loop
            )
        except RuntimeError:
            pass  # 无事件循环时跳过（测试环境）

    return ok(_task_to_order_info(task).model_dump())


@router.get("/orders", response_model=Envelope)
async def list_orders(
    demander_id: str = Query(...),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查询学员订单列表。"""
    tasks = server.task_repo.find_by_demander(demander_id)
    return ok(data=[_task_to_order_info(t).model_dump() for t in tasks])


@router.get("/orders/{task_id}", response_model=Envelope)
async def get_order(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查询单个订单详情。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    return ok(_task_to_order_info(task).model_dump())


@router.post("/orders/{task_id}/cancel", response_model=Envelope)
async def cancel_order(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """学员取消订单。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    try:
        task.cancel()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(_task_to_order_info(task).model_dump())


class ClaimRequest(BaseModel):
    coach_id: str


class CheckInOutRequest(BaseModel):
    coach_id: str
    lat: float
    lng: float


@router.post("/orders/{task_id}/claim", response_model=Envelope)
async def claim_order(
    task_id: str,
    req: ClaimRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练抢单：published/matching → assigned。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    task.bind_event_bus(server.event_bus)
    try:
        if task.status not in ("published", "matching"):
            raise RuntimeError(f"订单已被抢或状态不允许（当前: {task.status}）")
        task.assign_to(req.coach_id)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 广播给其他在线教练：订单已被抢
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        import asyncio
        message = {
            "type": "task.claimed",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"task_id": task_id, "coach_id": req.coach_id},
        }
        try:
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_online_coaches(message), loop
            )
        except RuntimeError:
            pass

    return ok(_task_to_order_info(task).model_dump())


@router.post("/orders/{task_id}/check-in", response_model=Envelope)
async def check_in_order(
    task_id: str,
    req: CheckInOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签到：assigned → in_progress。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    task.bind_event_bus(server.event_bus)
    try:
        task.start_execution()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 推送签到事件给学员
    server.event_bus.publish(
        Event(
            type=EventType.TASK_IN_SERVICE,
            source_layer="ESCORT",
            payload={
                "task_id": task_id,
                "demander_id": task.demander_id,
                "coach_id": req.coach_id,
                "lat": req.lat,
                "lng": req.lng,
            },
        )
    )
    return ok(_task_to_order_info(task).model_dump())


@router.post("/orders/{task_id}/check-out", response_model=Envelope)
async def check_out_order(
    task_id: str,
    req: CheckInOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签退：in_progress → completed。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    task.bind_event_bus(server.event_bus)
    try:
        task.complete()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(_task_to_order_info(task).model_dump())
