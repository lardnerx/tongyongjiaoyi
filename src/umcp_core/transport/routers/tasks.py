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


class CompositeSubtaskRequest(BaseModel):
    key: str
    domain_tag: str
    title: str = ""
    description: str = ""
    structured_fields: dict[str, Any] | None = None


class CreateCompositeTaskRequest(BaseModel):
    demander_id: str
    domain_tag: str
    subtasks: list[CompositeSubtaskRequest]
    dependencies: dict[str, list[str]] = {}


class CompositeSubtaskInfo(BaseModel):
    key: str
    task_id: str
    domain_tag: str
    status: str


class CompositeTaskInfo(BaseModel):
    task_id: str
    status: str
    subtasks: list[CompositeSubtaskInfo]


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
    """发布标准任务并匹配。

    注意：当前实现允许已认证用户用任意 demander_id 创建任务（规格简化）。
    生产环境应校验 req.demander_id == current_user.user_id。
    """
    task = StandardTask(
        demander_id=req.demander_id,
        domain_tag=DomainTag.of(req.domain_tag),
        title=req.title,
        description=req.description,
        structured_fields=req.structured_fields or {},
    )
    try:
        server.publish_and_match(task)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    return ok(_task_to_info(task))


@router.post("/composite", response_model=Envelope[CompositeTaskInfo])
async def create_composite_task(
    req: CreateCompositeTaskRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[CompositeTaskInfo]:
    """发布复合任务（跨 domain DAG 编排）。

    请求中的 ``dependencies`` 使用子任务 ``key`` 表达依赖，服务端转换为
    真实 task_id 后交给 ``CompositeTask`` 校验 DAG 并启动编排。
    """
    from umcp_core.core.composite_task import CompositeTask

    if not req.subtasks:
        raise IllegalStateError(message="subtasks 不能为空")
    keys = [s.key for s in req.subtasks]
    if len(set(keys)) != len(keys):
        raise IllegalStateError(message="subtask key 不能重复")

    built: list[StandardTask] = []
    id_by_key: dict[str, str] = {}
    for sub in req.subtasks:
        task = StandardTask(
            demander_id=req.demander_id,
            domain_tag=DomainTag.of(sub.domain_tag),
            title=sub.title,
            description=sub.description,
            structured_fields=sub.structured_fields or {},
        )
        built.append(task)
        id_by_key[sub.key] = task.task_id

    try:
        dependencies = {
            id_by_key[key]: [id_by_key[dep] for dep in deps]
            for key, deps in req.dependencies.items()
        }
    except KeyError as e:
        raise IllegalStateError(message=f"依赖引用了未知子任务: {e}") from e

    composite = CompositeTask(
        demander_id=req.demander_id,
        domain_tag=DomainTag.of(req.domain_tag),
        subtasks=built,
        dependencies=dependencies,
    )
    try:
        server.publish_and_match(composite)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e

    info = CompositeTaskInfo(
        task_id=composite.task_id,
        status=composite.status,
        subtasks=[
            CompositeSubtaskInfo(
                key=req_sub.key,
                task_id=task.task_id,
                domain_tag=task.domain_tag.value,
                status=task.status,
            )
            for task, req_sub in zip(built, req.subtasks)
        ],
    )
    return ok(info)


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
    tasks = server.task_repo.list_all()
    if status:
        tasks = [t for t in tasks if t.status == status]
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
    """取消任务。

    注意：当前未校验任务所属（规格简化）。生产环境应校验 task.demander_id == current_user.user_id。
    """
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"任务 {task_id} 不存在")
    try:
        task.cancel()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(message="已取消")


@router.post("/{task_id}/complete", response_model=Envelope)
async def complete_task(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """标记任务完成。

    注意：当前未校验任务所属（规格简化）。生产环境应校验 task.demander_id == current_user.user_id。
    """
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"任务 {task_id} 不存在")
    try:
        task.complete()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(message="已完成")
