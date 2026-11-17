"""站内通知（消息中心）router。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationItemResponse(BaseModel):
    """站内消息项。"""

    notification_id: int
    type: str
    title: str
    body: str
    is_read: bool
    created_at: str | None = None


class NotificationListResponse(BaseModel):
    """站内消息列表。"""

    items: list[NotificationItemResponse]
    total_unread: int


def _get_repo(server: UMCPServer) -> Any:
    repo = getattr(server, "notification_repo", None)
    if repo is None:
        raise IllegalStateError(message="通知仓储未注册")
    return repo


def _to_item(row: dict[str, Any]) -> NotificationItemResponse:
    created_at = row.get("created_at")
    return NotificationItemResponse(
        notification_id=row["notification_id"],
        type=row["type"],
        title=row["title"],
        body=row["body"],
        is_read=row.get("read_at") is not None,
        created_at=created_at.isoformat() if created_at else None,
    )


@router.get("", response_model=Envelope[NotificationListResponse])
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[NotificationListResponse]:
    """查询当前用户的站内消息（按时间倒序）。"""
    repo = _get_repo(server)
    rows = repo.list_by_user(
        current_user.user_id,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    data = NotificationListResponse(
        items=[_to_item(r) for r in rows],
        total_unread=repo.count_unread(current_user.user_id),
    )
    return ok(data=data)


@router.get("/unread-count", response_model=Envelope[dict])
async def unread_count(
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[dict]:
    """查询未读消息数。"""
    count = _get_repo(server).count_unread(current_user.user_id)
    return ok(data={"count": count})


@router.post("/read-all", response_model=Envelope[dict])
async def mark_all_read(
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[dict]:
    """全部标记为已读。"""
    marked = _get_repo(server).mark_all_read(current_user.user_id)
    return ok(data={"marked": marked})


@router.post("/{notification_id}/read", response_model=Envelope[dict])
async def mark_read(
    notification_id: int,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[dict]:
    """单条标记为已读。"""
    found = _get_repo(server).mark_read(current_user.user_id, notification_id)
    if not found:
        raise NotFoundError(message=f"消息 {notification_id} 不存在")
    return ok(data={"notification_id": notification_id})
