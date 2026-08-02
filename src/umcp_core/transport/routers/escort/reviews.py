"""陪驾评价 router（双向评价）。"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError, PermissionDeniedError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/escort", tags=["escort-reviews"])

# 内存存储（MVP 阶段，后续迁移到 ORM）
_reviews_store: dict[str, list[dict]] = {}
_review_locks: dict[str, threading.Lock] = {}
_review_locks_guard = threading.Lock()


def _get_review_lock(task_id: str) -> threading.Lock:
    """获取指定 task_id 的评价锁（线程安全）。"""
    with _review_locks_guard:
        if task_id not in _review_locks:
            _review_locks[task_id] = threading.Lock()
        return _review_locks[task_id]


class ReviewRequest(BaseModel):
    reviewer_id: str
    reviewer_role: str  # STUDENT | COACH
    ratings: dict[str, float]
    comment: str = ""


@router.post("/orders/{task_id}/reviews", response_model=Envelope)
async def create_review(
    task_id: str,
    req: ReviewRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """提交评价。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    if task.status != "completed":
        raise IllegalStateError(message=f"订单未完成（当前: {task.status}），无法评价")

    # 身份校验：只能为自己提交评价
    if current_user.user_id != req.reviewer_id:
        raise PermissionDeniedError(message="只能为自己提交评价")

    # 确定被评价者 + 参与方校验
    if req.reviewer_role == "STUDENT":
        if req.reviewer_id != task.demander_id:
            raise PermissionDeniedError(message="只有该订单的学员才能以学员身份评价")
        if not task.assigned_resource_id:
            raise IllegalStateError(message="订单未分配教练，无法评价")
        evaluatee_id = task.assigned_resource_id
    else:  # COACH
        if req.reviewer_id != task.assigned_resource_id:
            raise PermissionDeniedError(message="只有该订单的教练才能以教练身份评价")
        evaluatee_id = task.demander_id

    # 检查重复评价 + 写入（per-task_id 锁，避免 TOCTOU 竞态）
    with _get_review_lock(task_id):
        existing = _reviews_store.get(task_id, [])
        for r in existing:
            if r["reviewer_role"] == req.reviewer_role:
                raise IllegalStateError(message="该角色已评价过此订单")

        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()
        review = {
            "review_id": review_id,
            "task_id": task_id,
            "reviewer_id": req.reviewer_id,
            "reviewer_role": req.reviewer_role,
            "evaluatee_id": evaluatee_id,
            "ratings": req.ratings,
            "comment": req.comment,
            "created_at": now,
        }
        _reviews_store.setdefault(task_id, []).append(review)

    # 更新信任画像
    domain_tag = task.domain_tag.value
    trust_engine = server.trust_engine_for(domain_tag)
    if trust_engine is not None:
        evaluation = Evaluation(
            evaluator_id=req.reviewer_id,
            evaluatee_id=evaluatee_id,
            task_id=task_id,
            ratings=req.ratings,
            comment=req.comment,
            domain_tag=domain_tag,
        )
        trust_engine.record_evaluation(evaluation)

    # 发布评价事件
    server.event_bus.publish(
        Event(
            type=EventType.REVIEW_SUBMITTED,
            source_layer="ESCORT",
            payload={
                "task_id": task_id,
                "reviewer_id": req.reviewer_id,
                "evaluatee_id": evaluatee_id,
                "reviewer_role": req.reviewer_role,
            },
        )
    )

    return ok(review)


@router.get("/orders/{task_id}/reviews", response_model=Envelope)
async def get_reviews(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查询订单评价。"""
    reviews = _reviews_store.get(task_id, [])
    return ok(reviews)
