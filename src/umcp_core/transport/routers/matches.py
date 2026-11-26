"""匹配路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter()


class TriggerMatchRequest(BaseModel):
    task_id: str
    domain_tag: str


class MatchResultInfo(BaseModel):
    task_id: str
    matched: bool
    selected_resource_id: str | None = None
    candidates: list[str] = []


@router.post("", response_model=Envelope[MatchResultInfo])
async def trigger_match(
    req: TriggerMatchRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[MatchResultInfo]:
    """手动触发匹配。"""
    task = server.task_repo.find_by_id(req.task_id)
    if task is None:
        raise NotFoundError(message=f"任务 {req.task_id} 不存在")
    strategy = server.match_strategy_for(req.domain_tag)
    if strategy is None:
        raise NotFoundError(message=f"domain {req.domain_tag} 未注册匹配策略")
    candidates = server.match_candidates(task, req.domain_tag)
    result = strategy.execute(task, candidates)
    info = MatchResultInfo(
        task_id=result.task_id,
        matched=result.matched,
        selected_resource_id=result.selected_resource_id,
        candidates=result.candidates,
    )
    return ok(info)
