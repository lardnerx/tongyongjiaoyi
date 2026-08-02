"""陪驾订单 router（学员下单/取消/查询）。"""
from __future__ import annotations

import threading
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
from umcp_core.transport.errors import IllegalStateError, NotFoundError, PermissionDeniedError
from umcp_core.transport.schemas import Envelope, ok
from plugins.escort_driving.tasks import EscortTask

router = APIRouter(prefix="/api/v1/escort", tags=["escort-orders"])

# per-task_id 锁，确保抢单串行化（避免并发抢单竞态条件）
_claim_locks: dict[str, threading.Lock] = {}
_claim_locks_guard = threading.Lock()


def _get_claim_lock(task_id: str) -> threading.Lock:
    """获取指定 task_id 的锁（线程安全）。"""
    with _claim_locks_guard:
        if task_id not in _claim_locks:
            _claim_locks[task_id] = threading.Lock()
        return _claim_locks[task_id]


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
    """订单信息（实时单/预约单通用）。"""

    task_id: str
    order_type: str
    status: str
    demander_id: str
    car_type: str
    duration_hours: int
    assigned_resource_id: str | None = None
    title: str | None = None
    scheduled_at: str | None = None
    coach_level_pref: str | None = None
    deal_id: str | None = None


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
        scheduled_at=task.structured_fields.get("scheduled_at"),
        coach_level_pref=task.structured_fields.get("coach_level_pref"),
        deal_id=None,  # 由调用方按需填充（get_order 反查 deal_repo）
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
        task.publish_for_claim()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 广播给所有在线教练
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
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
            await manager.broadcast_to_online_coaches(message)
        except Exception:
            pass

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
    info = _task_to_order_info(task)
    # 预约单反查 deal_id
    if task.order_type == "SCHEDULED":
        deals = server.deal_repo.find_by_task(task_id)
        if deals:
            info.deal_id = deals[-1].deal_id  # 取最新 deal
    return ok(info.model_dump())


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
    # 越权校验：只能为自己抢单
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能为自己抢单")

    lock = _get_claim_lock(task_id)
    with lock:
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
        message = {
            "type": "task.claimed",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"task_id": task_id, "coach_id": req.coach_id},
        }
        try:
            await manager.broadcast_to_online_coaches(message)
        except Exception:
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
    # 越权校验：只能操作自己的订单
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能操作自己的订单")

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
    # 越权校验：只能操作自己的订单
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能操作自己的订单")

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


class SelectCoachRequest(BaseModel):
    resource_id: str


class SelectCoachResponse(BaseModel):
    deal_id: str
    task_id: str
    resource_id: str
    status: str
    deposit_amount: float


@router.post("/orders/{task_id}/select-coach", response_model=Envelope)
async def select_coach(
    task_id: str,
    req: SelectCoachRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """预约单：学员选择教练，创建 Deal(pending)。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    if task.order_type != "SCHEDULED":
        raise IllegalStateError(message="仅预约单支持选教练")
    if task.status != TaskStatus.DRAFT:
        raise IllegalStateError(message=f"订单状态 {task.status} 不允许选教练")

    # 校验 resource_id 在候选列表中（重新匹配验证）
    strategy = server.scheduled_match_strategy_for(task.domain_tag.value)
    if strategy is not None:
        candidates = server.resource_repo.list_all()
        domain_candidates = [r for r in candidates if r.domain_tag.value == task.domain_tag.value]
        result = strategy.execute(task, domain_candidates)
        if req.resource_id not in result.candidates:
            raise PermissionDeniedError(message="所选教练不在候选列表中")

    resource = server.resource_repo.find_by_id(req.resource_id)
    if resource is None:
        raise NotFoundError(message=f"教练 {req.resource_id} 不存在")

    # task: draft → published → assigned
    task.bind_event_bus(server.event_bus)
    try:
        task.publish_for_claim()
        task.assign_to(req.resource_id)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 计算定金：用 PaymentSchema 算总价，再取 30%
    from umcp_core.core.deal import Deal
    deal = Deal(
        task_id=task.task_id,
        resource_id=req.resource_id,
        demander_id=task.demander_id,
        supplier_id=resource.supplier_id,
    )
    deal.bind_event_bus(server.event_bus)

    schema = server.payment_schema_for(task.domain_tag.value)
    if schema is not None:
        payment_order = schema.calculate(task, deal)
        deposit_amount = round(payment_order.total_amount * 0.3, 2)
        deal.final_amount = payment_order.total_amount
    else:
        deposit_amount = 0.0

    server.deal_repo.save(deal)

    # 发布 DEAL_CREATED 事件（payload 含 supplier_id 供 WS 推送给教练）
    server.event_bus.publish(
        Event(
            type=EventType.DEAL_CREATED,
            source_layer="ESCORT",
            payload={
                "deal_id": deal.deal_id,
                "task_id": deal.task_id,
                "demander_id": deal.demander_id,
                "supplier_id": deal.supplier_id,
                "deposit_amount": deposit_amount,
            },
        )
    )

    return ok(
        SelectCoachResponse(
            deal_id=deal.deal_id,
            task_id=task.task_id,
            resource_id=req.resource_id,
            status=deal.status,
            deposit_amount=deposit_amount,
        ).model_dump()
    )
