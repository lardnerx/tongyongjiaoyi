"""信任路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import DomainTag
from umcp_core.layers.l5 import Evaluation
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter()


class TrustProfileInfo(BaseModel):
    user_id: str
    overall_score: float
    dimension_scores: dict[str, float]
    domain_tag: str = ""


class AggregateScoreInfo(BaseModel):
    user_id: str
    score: float
    domains: list[str]


class SubmitEvaluationRequest(BaseModel):
    evaluator_id: str
    evaluatee_id: str
    task_id: str
    ratings: dict[str, float]
    comment: str = ""
    domain_tag: str = ""


@router.get("/profiles/{user_id}", response_model=Envelope[TrustProfileInfo])
async def get_profile(
    user_id: str,
    domain_tag: str | None = None,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[TrustProfileInfo]:
    """查询用户信任画像。"""
    if domain_tag:
        profile = server.trust_repo.find_profile_by_domain(user_id, domain_tag)
    else:
        profile = server.trust_repo.find_profile(user_id)
    if profile is None:
        raise NotFoundError(message=f"用户 {user_id} 无信任画像")
    info = TrustProfileInfo(
        user_id=profile.user_id,
        overall_score=profile.overall_score,
        dimension_scores=profile.dimension_scores,
        domain_tag=profile.domain_tag,
    )
    return ok(info)


@router.get("/profiles/{user_id}/aggregate", response_model=Envelope[AggregateScoreInfo])
async def get_aggregate_score(
    user_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[AggregateScoreInfo]:
    """查询跨 domain 聚合信任分。"""
    score = server.aggregate_trust_score(user_id)
    domains = list(server._trust_engines.keys())
    info = AggregateScoreInfo(user_id=user_id, score=score, domains=domains)
    return ok(info)


@router.post("/evaluations", response_model=Envelope)
async def submit_evaluation(
    req: SubmitEvaluationRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """提交评价。"""
    evaluation = Evaluation(
        evaluator_id=req.evaluator_id,
        evaluatee_id=req.evaluatee_id,
        task_id=req.task_id,
        ratings=req.ratings,
        comment=req.comment,
        domain_tag=req.domain_tag,
    )
    server.trust_repo.save_evaluation(evaluation)
    # 更新信任画像（若注册了 trust_engine）
    if server.trust_engine and req.domain_tag:
        server.trust_engine.evaluate(req.evaluatee_id)
    return ok(message="评价已提交")
