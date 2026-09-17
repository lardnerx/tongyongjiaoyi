"""LBS 位置服务路由：附近搜索、位置更新、位置查询。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/lbs", tags=["lbs"])


@router.get("/nearby", response_model=Envelope)
async def nearby_coaches(
    lat: float = Query(..., description="当前纬度"),
    lng: float = Query(..., description="当前经度"),
    radius_km: float = Query(5.0, description="搜索半径（公里）"),
    server: UMCPServer = Depends(get_server),
    current_user: Any = Depends(get_current_user),
) -> Envelope:
    """查询附近在线的教练资源。"""
    lbs = getattr(server, "lbs_service", None)
    if lbs is None:
        return ok(data=[])

    # 获取在线教练列表
    manager = getattr(server, "ws_manager", None)
    online_coaches: set[str] = set()
    if manager is not None:
        online_coaches = getattr(manager, "online_coaches", set())

    # 查询附近位置
    nearby = lbs.nearby(lat, lng, radius_km)

    # 过滤出在线教练，并补齐距离信息
    results: list[dict[str, Any]] = []
    for loc in nearby:
        if loc["resource_id"] in online_coaches:
            results.append(loc)

    return ok(data=results)


@router.get("/coaches/{coach_id}/location", response_model=Envelope)
async def get_coach_location(
    coach_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: Any = Depends(get_current_user),
) -> Envelope:
    """查询指定教练的最新位置。"""
    lbs = getattr(server, "lbs_service", None)
    if lbs is None:
        raise NotFoundError(message="LBS 服务未启用")

    loc = lbs.get_location(coach_id)
    if loc is None:
        raise NotFoundError(message=f"教练 {coach_id} 位置信息不存在")

    return ok(data=loc)