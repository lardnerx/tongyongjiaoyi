"""任务路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, PaginatedData, ok, paginated

router = APIRouter()


class CreateTaskRequest(BaseModel):
    demander_id: str
    domain_tag: str
    title: str = ""
    description: str = ""
    structured_fields: dict[str, Any] | None = None


class TaskInfo(BaseModel):
    task_id: str
    demander_id: str
    domain_tag: str
    status: str
    title: str
    description: str
    assigned_resource_id: str | None = None


def _task_to_info(task: Any) -> TaskInfo:
    return TaskInfo(
        task_id=task.task_id,
        demander_id=task.demander_id,
        domain_tag=task.domain_tag.value,
        status=task.status,
        title=getattr(task, "title", ""),
        description=getattr(task, "description", ""),
        assigned_resource_id=task.assigned_resource_id,
    )


@router.post("", response_model=Envelope[TaskInfo])
async def create_task(
    req: CreateTaskRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[TaskInfo]:
    """发布标准任务并匹配。"""
    task = StandardTask(
        demander_id=req.demander_id,
        domain_tag=DomainTag.of(req.domain_tag),
        title=req.title,
        description=req.description,
        structured_fields=req.structured_fields or {},
    )
    server.publish_and_match(task)
    return ok(_task_to_info(task))


@router.get("", response_model=Envelope[PaginatedData[TaskInfo]])
async def list_tasks(
    status: str | None = None,
    domain_tag: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[TaskInfo]]:
    """查询任务列表。"""
    if status:
        domain = DomainTag.of(domain_tag) if domain_tag else None
        tasks = server.task_repo.find_by_status(status, domain)
    else:
        # 全量查询（内存仓储无全量方法，用 find_by_demander 兜底或遍历）
        # 简化：若 domain_tag 提供，按 domain 过滤；否则返回全部（内存仓储有 _tasks）
        tasks = list(getattr(server.task_repo, "_tasks", {}).values())
        if domain_tag:
            tasks = [t for t in tasks if t.domain_tag.value == domain_tag]

    total = len(tasks)
    start = (page - 1) * size
    end = start + size
    page_items = tasks[start:end]
    return paginated(
        items=[_task_to_info(t) for t in page_items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{task_id}", response_model=Envelope[TaskInfo])
async def get_task(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[TaskInfo]:
    """查询单任务详情。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"任务 {task_id} 不存在")
    return ok(_task_to_info(task))


@router.post("/{task_id}/cancel", response_model=Envelope)
async def cancel_task(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """取消任务。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"任务 {task_id} 不存在")
    try:
        task.cancel()
    except RuntimeError as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(message="已取消")


@router.post("/{task_id}/complete", response_model=Envelope)
async def complete_task(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """标记任务完成。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"任务 {task_id} 不存在")
    try:
        task.complete()
    except RuntimeError as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(message="已完成")
