"""事件查询路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import NotFoundError
from umcp_core.transport.schemas import Envelope, PaginatedData, ok, paginated

router = APIRouter()


class EventInfo(BaseModel):
    event_id: str
    type: str
    source_layer: str
    payload: dict[str, Any]
    timestamp: float


def _event_to_info(event: Any) -> EventInfo:
    return EventInfo(
        event_id=event.event_id,
        type=event.type.value if hasattr(event.type, "value") else str(event.type),
        source_layer=event.source_layer,
        payload=event.payload or {},
        timestamp=event.timestamp,
    )


@router.get("", response_model=Envelope[PaginatedData[EventInfo]])
async def list_events(
    event_type: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[EventInfo]]:
    """查询事件日志。"""
    events = server.event_bus.history()
    if event_type:
        events = [
            e for e in events
            if (e.type.value if hasattr(e.type, "value") else str(e.type)) == event_type
        ]

    total = len(events)
    start = (page - 1) * size
    end = start + size
    page_items = events[start:end]
    return paginated(
        items=[_event_to_info(e) for e in page_items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{event_id}", response_model=Envelope[EventInfo])
async def get_event(
    event_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[EventInfo]:
    """查询单事件详情。"""
    events = server.event_bus.history()
    for e in events:
        if e.event_id == event_id:
            return ok(_event_to_info(e))
    raise NotFoundError(message=f"事件 {event_id} 不存在")
