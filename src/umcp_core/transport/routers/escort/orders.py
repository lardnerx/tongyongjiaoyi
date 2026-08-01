"""陪驾订单 router（学员下单/取消/查询）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import DomainTag
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

    # 实时单：publish + match + assign + start（不自动 complete，
    # 等待教练接单/签到/签退后才由后续流程推进到 COMPLETED）
    try:
        server.task_repo.save(task)
        task.bind_event_bus(server.event_bus)
        task.publish()
        strategy = server.match_strategy_for(req.domain_tag)
        if strategy is None:
            raise IllegalStateError(
                message=f"domain {req.domain_tag} 未注册匹配策略"
            )
        candidates = server.resource_repo.find_available(task.domain_tag)
        result = strategy.execute(task, candidates)
        if result.matched:
            task.assign_to(result.selected_resource_id)
            task.start_execution()
        else:
            task.cancel()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
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
