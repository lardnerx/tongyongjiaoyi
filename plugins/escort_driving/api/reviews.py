"""陪驾评价 router（双向评价）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

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


class ReviewRequest(BaseModel):
    reviewer_id: str
    reviewer_role: str  # STUDENT | COACH
    ratings: dict[str, float]
    comment: str = ""


def _to_api(record: dict[str, Any]) -> dict[str, Any]:
    """仓储记录转 HTTP 出参：created_at 统一序列化为带时区的 ISO 字符串。"""
    item = dict(record)
    created_at = item.get("created_at")
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        item["created_at"] = created_at.isoformat()
    return item


@router.post("/orders/{task_id}/reviews", response_model=Envelope)
async def create_review(
    task_id: str,
    req: ReviewRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """提交评价（持久化到 review_repo）。"""
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

    # 同一角色每个订单只能评价一次（仓储层唯一约束兜底并发）
    existing = server.review_repo.find_by_task(task_id)
    for r in existing:
        if r["reviewer_role"] == req.reviewer_role:
            raise IllegalStateError(message="该角色已评价过此订单")

    review = {
        "review_id": f"rev_{uuid.uuid4().hex[:12]}",
        "task_id": task_id,
        "reviewer_id": req.reviewer_id,
        "reviewer_role": req.reviewer_role,
        "evaluatee_id": evaluatee_id,
        "ratings": req.ratings,
        "comment": req.comment,
        "created_at": datetime.utcnow(),
    }
    try:
        saved = server.review_repo.save(review)
    except ValueError as e:
        raise IllegalStateError(message=str(e)) from e

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
        profile = trust_engine.record_evaluation(evaluation)
        # 持久化画像，供 /trust/profiles 与跨 domain 聚合读取
        if getattr(server, "trust_repo", None) is not None:
            profile.domain_tag = domain_tag
            server.trust_repo.save_profile(profile)

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

    return ok(_to_api(saved))


@router.get("/orders/{task_id}/reviews", response_model=Envelope)
async def get_reviews(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查询订单评价。"""
    reviews = server.review_repo.find_by_task(task_id)
    return ok([_to_api(r) for r in reviews])
