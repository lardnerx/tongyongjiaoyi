"""陪驾订单 router（学员下单/取消/查询）。"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import ResourceStatus
from umcp_core.core.task import TaskStatus
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import (
    IllegalStateError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from umcp_core.transport.schemas import Envelope, ok
from ..tasks import EscortTask

router = APIRouter(prefix="/api/v1/escort", tags=["escort-orders"])

logger = logging.getLogger(__name__)

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
    origin_address: str | None = None
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
    origin_address: str | None = None
    origin_lat: float | None = None
    origin_lng: float | None = None
    duration_hours: int
    assigned_resource_id: str | None = None
    title: str | None = None
    scheduled_at: str | None = None
    coach_level_pref: str | None = None
    deal_id: str | None = None
    cancel_penalty: float = 0.0
    created_at: str | None = None
    check_in_at: str | None = None
    check_out_at: str | None = None
    customer_confirmed_at: str | None = None
    settled_amount: float | None = None


class ScheduledOrderInfo(BaseModel):
    """预约单信息（含候选教练）。"""

    task_id: str
    order_type: str
    candidates: list[str]


def _order_type_of(task: EscortTask) -> str:
    """取订单类型。

    仓储往返后插件任务会被还原为 StandardTask，此时 order_type 只存在于
    structured_fields 中（历史数据两者都没有，按实时单兜底）。
    """
    return (
        getattr(task, "order_type", None)
        or task.structured_fields.get("order_type")
        or "REALTIME"
    )


def _iso_utc(dt: datetime | None) -> str | None:
    """序列化为带时区的 ISO 字符串。

    Task.created_at 由 datetime.utcnow() 生成（naive，实际是 UTC）。若直接
    isoformat()，前端 new Date() 会按本地时区解析，东八区会凭空早 8 小时，
    导致刚下的单立刻显示「已超时」。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _pick_coaches_for_order(
    server: Any, lat: float, lng: float, radius_km: float
) -> list[str]:
    """按半径筛选在线教练，返回应向其推送的 coach_id 列表。

    - radius_km <= 0 或未启用 LBS：不限制距离，推给所有在线教练
    - 否则只推给「在线 且 最新位置在半径内」的教练
    """
    manager = getattr(server, "ws_manager", None)
    online = list(manager.online_suppliers) if manager is not None else []
    lbs = getattr(server, "lbs_service", None)
    if lbs is None or radius_km <= 0:
        return online
    nearby_ids = {loc["resource_id"] for loc in lbs.nearby(lat, lng, radius_km)}
    nearby_online = [uid for uid in online if uid in nearby_ids]
    # 半径内没有在线司机时退化为全量在线司机，避免订单无人可推
    return nearby_online or online


def _latest_deal(server: Any, task_id: str):
    """取任务最新一笔交易（实时单与预约单都由 Deal 承载资金状态）。"""
    deals = server.deal_repo.find_by_task(task_id)
    return deals[-1] if deals else None


def _quote_deal(server: Any, task: Any, deal: Any) -> None:
    """用 PaymentSchema 报价，并把总价/佣金/分账锁定到 Deal。

    报价在抢单或选教练时一次性完成，后续结算复用 ``deal.final_amount``，
    运营改价不会影响已成交订单。
    """
    schema = server.payment_schema_for(task.domain_tag.value)
    if schema is None:
        return
    order = schema.calculate(task, deal)
    deal.final_amount = order.total_amount
    deal.metadata.update(
        {
            "pricing": order.metadata,
            "commission": order.commission,
            "supplier_amount": order.supplier_amount,
        }
    )


# ---------------------------------------------------------------------------
# 抢单准入（L7）
#
# 准入数据有两个来源：
# - 用户档案：user.metadata["credentials"]
# - L2 教练资源：resource.capabilities 中已认证且未过期的 certification
#
# 迁移策略（保证历史教练不被一次性拦死）：
# 1. 平台尚未采集任何准入数据（无资源、无凭证声明、无评价）→ 放行并告警；
# 2. 已声明资质但缺 coach_license → 拒绝（数据明确不具备该资质）；
# 3. 有档案但尚无评价 → 只校验资质，信任分从宽（否则新教练永远接不到
#    第一单，也就无法积累评价）；
# 4. 有评价 → 完整走 server.rule_engine（plugin.json 的
#    access_rule_expression）校验资质与信任分。
# ---------------------------------------------------------------------------

_REQUIRED_COACH_CREDENTIAL = "coach_license"
_ADMISSION_TRUST_FLOOR = 4.0


class _AdmissionUser(User):
    """准入校验用的最小 User 实现（凭证来自档案与 L2 资源）。"""

    def authenticate(self, credential: Any) -> bool:
        return True


def _coach_admission_profile(
    server: Any, coach_id: str, task: Any
) -> tuple[set[str], bool, bool, bool, bool, float]:
    """汇总教练的准入数据。

    Returns:
        (credentials, credential_declared, resource_found,
         resource_disabled, rated, trust_score)
    """
    credentials: set[str] = set()
    credential_declared = False
    user = server.user_repo.find_by_id(coach_id) if server.user_repo else None
    if user is not None:
        user_credentials = set(user.metadata.get("credentials") or [])
        if user_credentials:
            credential_declared = True
            credentials.update(user_credentials)

    resource_found = False
    resource_disabled = False
    resources = (
        server.resource_repo.find_by_supplier(coach_id)
        if server.resource_repo
        else []
    )
    for resource in resources:
        if resource.domain_tag.value != task.domain_tag.value:
            continue
        resource_found = True
        if resource.status == ResourceStatus.DISABLED:
            resource_disabled = True
        for cap in resource.capabilities:
            if cap.type != "certification":
                continue
            # 资源登记了资质即视为平台已采集资质数据：
            # 未认证/已过期同样算「已声明但无效」，不能按缺失宽限。
            credential_declared = True
            if cap.is_valid():
                credentials.add(cap.name)

    engine = server.trust_engine_for(task.domain_tag.value)
    profile = engine.evaluate(coach_id) if engine is not None else None
    rated = profile is not None and any(
        score > 0 for score in profile.dimension_scores.values()
    )
    return (
        credentials,
        credential_declared,
        resource_found,
        resource_disabled,
        rated,
        profile.overall_score if profile is not None else 0.0,
    )


def _check_claim_admission(server: Any, coach_id: str, task: Any) -> None:
    """抢单前 L7 准入校验，未通过抛 403（不改变 Task/Deal）。"""
    (
        credentials,
        credential_declared,
        resource_found,
        resource_disabled,
        rated,
        trust_score,
    ) = _coach_admission_profile(server, coach_id, task)

    if resource_disabled:
        raise PermissionDeniedError(message="教练资源已被禁用，无法接单")

    if not (resource_found or credential_declared or rated):
        logger.warning(
            "[ESCORT][ADMISSION] 教练 %s 无准入档案，按迁移宽限放行", coach_id
        )
        return

    licensed = _REQUIRED_COACH_CREDENTIAL in credentials
    if credential_declared and not licensed:
        raise PermissionDeniedError(
            message=f"未通过准入校验：缺少教练资质（{_REQUIRED_COACH_CREDENTIAL}）"
        )

    if not rated:
        logger.info(
            "[ESCORT][ADMISSION] 教练 %s 尚无评价记录，信任分从宽", coach_id
        )
        return

    if licensed:
        subject = _AdmissionUser(
            user_id=coach_id,
            metadata={"credentials": sorted(credentials)},
        )
        passed = server.rule_engine.check_access(subject, task)
    else:
        passed = trust_score >= _ADMISSION_TRUST_FLOOR
    if not passed:
        raise PermissionDeniedError(
            message=(
                f"未通过准入校验：信任分 {trust_score:.2f} "
                f"低于要求 {_ADMISSION_TRUST_FLOOR}"
            )
        )


# ---------------------------------------------------------------------------
# 履约状态同步
#
# Task 是履约权威源：published → assigned → in_progress → completed；
# Deal 是资金/确认权威源：pending → active → in_service → completed。
# 两者通过 task_id 一一绑定。所有签到/签退入口都必须走下面的函数，
# 避免出现「Task 已完成、Deal 还在服务中」这类状态分叉。
# ---------------------------------------------------------------------------


def _sync_deal_status(server: Any, deal: Deal | None, target: str) -> bool:
    """把 Deal 推进到 target，必要时补齐中间态；返回是否发生变化。

    已处于终态（cancelled / resolved）的交易拒绝继续履约，避免给已取消订单
    提供服务。
    """
    if deal is None or deal.status == target:
        return False
    if deal.status in (DealStatus.CANCELLED, DealStatus.RESOLVED):
        raise IllegalStateError(message=f"交易状态 {deal.status} 不允许继续履约")

    deal.bind_event_bus(server.event_bus)
    changed = False
    try:
        while deal.status != target:
            if deal.status == DealStatus.PENDING:
                deal.activate()
            elif deal.status == DealStatus.ACTIVE:
                if target == DealStatus.COMPLETED:
                    deal.complete()
                else:
                    deal.check_in()
            elif deal.status == DealStatus.IN_SERVICE:
                deal.complete()
            else:
                break
            changed = True
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    if changed:
        server.deal_repo.save(deal)
    return changed


def apply_check_in(
    server: Any,
    task: Any | None,
    deal: Deal | None,
    coach_id: str = "",
    lat: float | None = None,
    lng: float | None = None,
) -> None:
    """签到：Task assigned → in_progress，Deal 跟随到 in_service。

    重复签到幂等（网络重试不应报错）。历史无 Task 的旧交易（task 为 None）
    只推进 Deal，保证兼容。
    """
    task_started = False
    if task is not None:
        if task.status == TaskStatus.IN_PROGRESS:
            pass
        elif task.status == TaskStatus.ASSIGNED:
            task.bind_event_bus(server.event_bus)
            try:
                task.start_execution()
            except (RuntimeError, ValueError) as e:
                raise IllegalStateError(message=str(e)) from e
            task.structured_fields["check_in_at"] = _iso_utc(datetime.utcnow())
            server.task_repo.save(task)
            task_started = True
        else:
            raise IllegalStateError(message=f"订单状态 {task.status} 不允许签到")

    _sync_deal_status(server, deal, DealStatus.IN_SERVICE)

    if task_started and task is not None:
        server.event_bus.publish(
            Event(
                type=EventType.TASK_IN_SERVICE,
                source_layer="ESCORT",
                payload={
                    "task_id": task.task_id,
                    "demander_id": task.demander_id,
                    "coach_id": coach_id,
                    "lat": lat,
                    "lng": lng,
                },
            )
        )


def apply_check_out(
    server: Any,
    task: Any | None,
    deal: Deal | None,
) -> None:
    """签退：Task in_progress → completed，Deal 跟随到 completed。

    重复签退幂等；历史无 Task 的旧交易只推进 Deal。
    """
    if task is not None:
        if task.status == TaskStatus.COMPLETED:
            pass
        elif task.status == TaskStatus.IN_PROGRESS:
            task.bind_event_bus(server.event_bus)
            try:
                task.complete()
            except (RuntimeError, ValueError) as e:
                raise IllegalStateError(message=str(e)) from e
            now = datetime.utcnow()
            task.structured_fields["check_out_at"] = _iso_utc(now)
            # 记录实际服务时长，供结算页使用
            check_in_raw = task.structured_fields.get("check_in_at")
            if check_in_raw:
                try:
                    check_in_dt = datetime.fromisoformat(check_in_raw)
                    if check_in_dt.tzinfo is not None:
                        check_in_dt = check_in_dt.astimezone(timezone.utc).replace(
                            tzinfo=None
                        )
                    actual_hours = (now - check_in_dt).total_seconds() / 3600
                    task.custom_fields["actual_hours"] = round(actual_hours, 2)
                except (ValueError, TypeError):
                    pass
            server.task_repo.save(task)
        else:
            raise IllegalStateError(message=f"订单状态 {task.status} 不允许签退")

    _sync_deal_status(server, deal, DealStatus.COMPLETED)


def _task_to_order_info(task: EscortTask) -> OrderInfo:
    return OrderInfo(
        task_id=task.task_id,
        order_type=_order_type_of(task),
        status=task.status,
        demander_id=task.demander_id,
        car_type=task.structured_fields.get("car_type", ""),
        origin_address=task.structured_fields.get("origin_address"),
        origin_lat=(
            task.spatio_temporal.origin_lat if task.spatio_temporal else None
        ),
        origin_lng=(
            task.spatio_temporal.origin_lng if task.spatio_temporal else None
        ),
        duration_hours=task.structured_fields.get("duration_hours", 0),
        assigned_resource_id=task.assigned_resource_id,
        title=task.title,
        scheduled_at=task.structured_fields.get("scheduled_at"),
        coach_level_pref=task.structured_fields.get("coach_level_pref"),
        deal_id=None,  # 由调用方按需填充（get_order 反查 deal_repo）
        created_at=_iso_utc(task.created_at),
        check_in_at=task.structured_fields.get("check_in_at"),
        check_out_at=task.structured_fields.get("check_out_at"),
        customer_confirmed_at=task.structured_fields.get("customer_confirmed_at"),
        settled_amount=task.structured_fields.get("settled_amount"),
    )


def _calculate_scheduled_penalty(
    rule_config,
    scheduled_at: datetime | None,
    now: datetime | None = None,
) -> float:
    """根据预约单取消规则计算罚分。

    Args:
        rule_config: RuleConfig 实例（可为 None，返回 0）
        scheduled_at: 预约时间
        now: 当前时间（测试可注入），默认 datetime.utcnow()

    Returns:
        罚分分值（0.0 表示无罚分）
    """
    if rule_config is None or scheduled_at is None:
        return 0.0
    tiers = rule_config.get("escort.cancel.scheduled.penalty_tiers")
    if not tiers or not isinstance(tiers, list):
        return 0.0
    now = now or datetime.utcnow()
    hours_before = (scheduled_at - now).total_seconds() / 3600.0
    # 找到第一个 hours_before >= tier.hours_before 的档位
    for tier in tiers:
        if hours_before >= tier.get("hours_before", 0):
            return float(tier.get("penalty", 0.0))
    # 所有档位都不匹配（理论上最后 hours_before=0 档会兜底）
    return 0.0


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
        origin_address=req.origin_address,
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

    # 推送给半径内的在线教练（规则 escort.match.realtime.radius_km，<=0 不限）
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
                "origin_address": req.origin_address,
                "car_type": req.car_type,
                "duration_hours": req.duration_hours,
                "coach_level_pref": req.coach_level_pref,
                "created_at": _iso_utc(task.created_at),
            },
        }
        rule_config = getattr(server, "rule_config", None)
        radius_km = (
            rule_config.get("escort.match.realtime.radius_km", default=5.0)
            if rule_config is not None
            else 5.0
        )
        target_coach_ids = _pick_coaches_for_order(
            server, req.origin_lat, req.origin_lng, radius_km
        )
        try:
            await manager.broadcast_to_suppliers(message, target_coach_ids)
        except Exception:
            pass

    return ok(_task_to_order_info(task).model_dump())


@router.get("/orders", response_model=Envelope)
async def list_orders(
    demander_id: str | None = Query(None),
    coach_id: str | None = Query(None),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查询订单列表：学员按下单者查，司机按接单者查（均按下单时间倒序）。"""
    if coach_id:
        tasks = [
            t for t in server.task_repo.list_all() if t.assigned_resource_id == coach_id
        ]
    elif demander_id:
        tasks = server.task_repo.find_by_demander(demander_id)
    else:
        raise ValidationError(message="demander_id 或 coach_id 至少提供一个")
    orders = [_task_to_order_info(t).model_dump() for t in tasks]
    orders.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return ok(data=orders)


@router.get("/orders/available", response_model=Envelope)
async def list_available_orders(
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """司机接单大厅：拉取当前可抢的实时单（published 状态）。

    WebSocket 推送是实时通道，司机进入大厅或刷新页面时需要主动拉取，
    避免错过下单时不在线的订单。
    """
    tasks = server.task_repo.find_by_status(TaskStatus.PUBLISHED)
    available = [
        _task_to_order_info(t).model_dump()
        for t in tasks
        if t.domain_tag.value == "escort" and _order_type_of(t) == "REALTIME"
    ]
    # 新单在前
    available.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return ok(data=available)


@router.get("/orders/balance", response_model=Envelope)
async def get_coach_balance(
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """司机余额：已接订单中客户已确认支付的结算金额合计。"""
    tasks = [
        t
        for t in server.task_repo.list_all()
        if t.assigned_resource_id == current_user.user_id
    ]
    paid_tasks = [t for t in tasks if t.structured_fields.get("customer_confirmed_at")]
    balance = round(
        sum(float(t.structured_fields.get("settled_amount") or 0) for t in paid_tasks), 2
    )
    return ok(data={"balance": balance, "order_count": len(paid_tasks)})


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
    # 实时单与预约单都通过 Deal 承载资金状态，统一反查最新 deal
    deal = _latest_deal(server, task_id)
    if deal is not None:
        info.deal_id = deal.deal_id
    return ok(info.model_dump())


@router.post("/orders/{task_id}/cancel", response_model=Envelope)
async def cancel_order(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """学员取消订单。

    - 实时单：无罚分，直接 task.cancel()
    - 预约单：按规则梯度扣信用分；若已支付定金则触发退款
    """
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    if task.demander_id != current_user.user_id:
        raise PermissionDeniedError(message="只能取消自己的订单")
    # 服务已开始或已结束的订单不允许取消，避免司机服务中被单方面终止
    if task.status == TaskStatus.IN_PROGRESS:
        raise IllegalStateError(message="订单已开始服务，不能取消")
    if task.status == TaskStatus.COMPLETED:
        raise IllegalStateError(message="订单已完成，不能取消")

    rule_config = getattr(server, "rule_config", None)
    penalty = 0.0

    # 预约单：计算罚分并扣除信用分
    if _order_type_of(task) == "SCHEDULED":
        scheduled_at = getattr(task, "scheduled_at", None)
        penalty = _calculate_scheduled_penalty(rule_config, scheduled_at)
        if penalty > 0:
            engine = server.trust_engine_for(task.domain_tag.value)
            if engine is not None:
                engine.apply_penalty(
                    task.demander_id, penalty, reason="预约单取消"
                )

    # 取消 task
    task.bind_event_bus(server.event_bus)
    try:
        task.cancel()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 取消关联 deal 并退款（预约单定金、实时单报价都挂在 Deal 上）
    deals = server.deal_repo.find_by_task(task_id)
    payment_service = getattr(server, "payment_service", None)
    for deal in deals:
        if deal.status in ("pending", "active"):
            deal.bind_event_bus(server.event_bus)
            try:
                deal.cancel()
                server.deal_repo.save(deal)
            except (RuntimeError, ValueError):
                pass
        # 退款已支付的定金
        if payment_service is not None:
            records = payment_service.repo.find_by_deal(deal.deal_id)
            for record in records:
                if record["status"] == "paid":
                    try:
                        payment_service.refund(
                            payment_id=record["payment_id"],
                            amount=record["amount"],
                            reason="学员取消订单",
                        )
                    except Exception:
                        pass

    info = _task_to_order_info(task)
    info.cancel_penalty = penalty
    return ok(info.model_dump())


class CancelRulesResponse(BaseModel):
    """取消规则响应。"""

    timeout_seconds: int
    expand_after_seconds: int
    penalty_tiers: list[dict[str, Any]]


@router.get("/cancel-rules", response_model=Envelope)
async def get_cancel_rules(
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """返回当前取消规则配置（供前端倒计时与罚分提示）。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")

    return ok(
        CancelRulesResponse(
            timeout_seconds=rule_config.get(
                "escort.cancel.realtime.timeout_seconds", default=300
            ),
            expand_after_seconds=rule_config.get(
                "escort.cancel.realtime.expand_after_seconds", default=30
            ),
            penalty_tiers=rule_config.get(
                "escort.cancel.scheduled.penalty_tiers", default=[]
            ),
        ).model_dump()
    )


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
        if task.status not in ("published", "matching"):
            raise IllegalStateError(
                message=f"订单已被抢或状态不允许（当前: {task.status}）"
            )
        # L7 准入：凭证/资源/信任分不达标直接 403，订单保持 published
        _check_claim_admission(server, req.coach_id, task)
        try:
            task.assign_to(req.coach_id)
        except (RuntimeError, ValueError) as e:
            raise IllegalStateError(message=str(e)) from e
        server.task_repo.save(task)

    # 抢单成功即建立交易：报价走 PaymentSchema，状态置 ACTIVE（实时单为后付费）
    deal = _latest_deal(server, task_id)
    if deal is None:
        deal = Deal(
            task_id=task_id,
            resource_id=req.coach_id,
            demander_id=task.demander_id,
            supplier_id=req.coach_id,
            metadata={"order_type": "REALTIME"},
        )
        _quote_deal(server, task, deal)
        deal.bind_event_bus(server.event_bus)
        try:
            deal.activate()  # pending → active；DEAL_PAID 事件复用作「订单已确认」通知
        except (RuntimeError, ValueError) as e:
            raise IllegalStateError(message=str(e)) from e
        server.deal_repo.save(deal)

    # 广播给其他在线教练：订单已被抢
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        message = {
            "type": "task.claimed",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"task_id": task_id, "coach_id": req.coach_id},
        }
        try:
            await manager.broadcast_to_online_suppliers(message)
        except Exception:
            pass

    info = _task_to_order_info(task)
    info.deal_id = deal.deal_id
    return ok(info.model_dump())


@router.post("/orders/{task_id}/check-in", response_model=Envelope)
async def check_in_order(
    task_id: str,
    req: CheckInOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签到：assigned → in_progress（Deal 同步 active → in_service）。"""
    # 越权校验：只能操作自己的订单
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能操作自己的订单")

    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    deal = _latest_deal(server, task_id)
    apply_check_in(server, task, deal, req.coach_id, req.lat, req.lng)

    info = _task_to_order_info(task)
    if deal is not None:
        info.deal_id = deal.deal_id
    return ok(info.model_dump())


@router.post("/orders/{task_id}/check-out", response_model=Envelope)
async def check_out_order(
    task_id: str,
    req: CheckInOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签退：in_progress → completed（Deal 同步 in_service → completed）。"""
    # 越权校验：只能操作自己的订单
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能操作自己的订单")

    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    deal = _latest_deal(server, task_id)
    apply_check_out(server, task, deal)

    info = _task_to_order_info(task)
    if deal is not None:
        info.deal_id = deal.deal_id
    return ok(info.model_dump())


@router.post("/orders/{task_id}/confirm", response_model=Envelope)
async def confirm_order_payment(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """客户确认完成订单并支付（Mock 支付）。

    金额由 PaymentSchema 计算（车型单价 × 预定时长），佣金与分账回写 Deal。
    客户在「我的订单」已完成列表中确认后调用；重复确认幂等返回。
    """
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    if current_user.user_id != task.demander_id:
        raise PermissionDeniedError(message="只能确认自己的订单")
    if task.status != TaskStatus.COMPLETED:
        raise IllegalStateError(message=f"订单状态 {task.status} 不允许确认支付")
    if task.structured_fields.get("customer_confirmed_at"):
        return ok(_task_to_order_info(task).model_dump())

    deal = _latest_deal(server, task_id)
    # 历史订单可能没有 Deal，用临时交易完成计价，不落库
    pricing_deal = deal or Deal(
        task_id=task.task_id,
        resource_id=task.assigned_resource_id or "",
        demander_id=task.demander_id,
        supplier_id=task.assigned_resource_id or "",
    )
    schema = server.payment_schema_for(task.domain_tag.value)
    if schema is None:
        raise IllegalStateError(message="支付方案未注册")
    order = schema.calculate(task, pricing_deal)

    task.structured_fields["customer_confirmed_at"] = _iso_utc(datetime.utcnow())
    task.structured_fields["settled_amount"] = order.total_amount
    task.structured_fields["commission"] = order.commission
    task.structured_fields["supplier_amount"] = order.supplier_amount
    server.task_repo.save(task)

    if deal is not None:
        deal.final_amount = order.total_amount
        deal.metadata.update(
            {
                "commission": order.commission,
                "supplier_amount": order.supplier_amount,
                "pricing": order.metadata,
                "settled_at": datetime.utcnow().isoformat(),
            }
        )
        server.deal_repo.save(deal)

    info = _task_to_order_info(task)
    info.deal_id = deal.deal_id if deal is not None else None
    return ok(info.model_dump())


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
    if _order_type_of(task) != "SCHEDULED":
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

    # 计算定金：PaymentSchema 报价后取 metadata.deposit_amount（比例来自规则配置）
    deal = Deal(
        task_id=task.task_id,
        resource_id=req.resource_id,
        demander_id=task.demander_id,
        supplier_id=resource.supplier_id,
    )
    deal.bind_event_bus(server.event_bus)
    _quote_deal(server, task, deal)
    deposit_amount = float(deal.metadata.get("pricing", {}).get("deposit_amount", 0.0))

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
