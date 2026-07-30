"""资源路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource, ResourceStatus
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError, ValidationError
from umcp_core.transport.schemas import Envelope, PaginatedData, ok, paginated

router = APIRouter()


class CapabilityModel(BaseModel):
    type: str
    name: str
    value: str = ""
    verified: bool = False


class RegisterResourceRequest(BaseModel):
    supplier_id: str
    domain_tag: str
    resource_type: str = "generic"
    capabilities: list[CapabilityModel] = []
    metadata: dict[str, Any] | None = None


class ResourceInfo(BaseModel):
    resource_id: str
    supplier_id: str
    domain_tag: str
    resource_type: str
    status: str


class UpdateStatusRequest(BaseModel):
    status: str


class _GenericResource(Resource):
    """通用资源（HTTP 注册用，无特定子类）。"""

    def __init__(self, resource_type: str = "generic", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._resource_type = resource_type

    def resource_type(self) -> str:
        return self._resource_type


def _resource_to_info(res: Resource) -> ResourceInfo:
    return ResourceInfo(
        resource_id=res.resource_id,
        supplier_id=res.supplier_id,
        domain_tag=res.domain_tag.value,
        resource_type=res.resource_type(),
        status=res.status,
    )


@router.post("", response_model=Envelope[ResourceInfo])
async def register_resource(
    req: RegisterResourceRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[ResourceInfo]:
    """注册资源。"""
    caps = [
        Capability(type=c.type, name=c.name, value=c.value, verified=c.verified)
        for c in req.capabilities
    ]
    res = _GenericResource(
        resource_type=req.resource_type,
        supplier_id=req.supplier_id,
        domain_tag=DomainTag.of(req.domain_tag),
        capabilities=caps,
        metadata=req.metadata or {},
    )
    try:
        res.register()  # OFFLINE → IDLE
    except RuntimeError as e:
        raise IllegalStateError(message=str(e)) from e
    server.resource_repo.save(res)
    return ok(_resource_to_info(res))


@router.get("", response_model=Envelope[PaginatedData[ResourceInfo]])
async def list_resources(
    domain_tag: str | None = None,
    status: str | None = None,
    supplier_id: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[ResourceInfo]]:
    """查询资源列表。"""
    all_resources = server.resource_repo.list_all()
    if domain_tag:
        all_resources = [r for r in all_resources if r.domain_tag.value == domain_tag]
    if status:
        all_resources = [r for r in all_resources if r.status == status]
    if supplier_id:
        all_resources = [r for r in all_resources if r.supplier_id == supplier_id]

    total = len(all_resources)
    start = (page - 1) * size
    end = start + size
    page_items = all_resources[start:end]
    return paginated(
        items=[_resource_to_info(r) for r in page_items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{resource_id}", response_model=Envelope[ResourceInfo])
async def get_resource(
    resource_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[ResourceInfo]:
    """查询单资源详情。"""
    res = server.resource_repo.find_by_id(resource_id)
    if res is None:
        raise NotFoundError(message=f"资源 {resource_id} 不存在")
    return ok(_resource_to_info(res))


@router.post("/{resource_id}/status", response_model=Envelope)
async def update_resource_status(
    resource_id: str,
    req: UpdateStatusRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """更新资源状态。"""
    res = server.resource_repo.find_by_id(resource_id)
    if res is None:
        raise NotFoundError(message=f"资源 {resource_id} 不存在")
    try:
        res.update_status(req.status)
    except ValueError as e:
        raise ValidationError(message=str(e)) from e
    server.resource_repo.save(res)
    return ok(message="状态已更新")
