"""内存 LBS 实现（开发与测试用，基于 haversine 公式）。"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from umcp_core.shared.lbs.base import LBSService

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """haversine 公式计算球面距离（公里）。"""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class InMemoryLBSService(LBSService):
    """内存 LBS 服务。"""

    def __init__(self) -> None:
        self._locations: dict[str, dict[str, Any]] = {}

    def update_location(
        self, resource_id: str, lat: float, lng: float, heading: float = 0.0, speed: float = 0.0
    ) -> None:
        self._locations[resource_id] = {
            "resource_id": resource_id,
            "lat": lat,
            "lng": lng,
            "heading": heading,
            "speed": speed,
            "updated_at": datetime.utcnow(),
        }

    def get_location(self, resource_id: str) -> dict[str, Any] | None:
        loc = self._locations.get(resource_id)
        return dict(loc) if loc else None

    def nearby(
        self, lat: float, lng: float, radius_km: float, level: str | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for loc in self._locations.values():
            d = _haversine_km(lat, lng, loc["lat"], loc["lng"])
            if d <= radius_km:
                results.append({**loc, "distance_km": d})
        results.sort(key=lambda x: x["distance_km"])
        return results

    def distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        return _haversine_km(lat1, lng1, lat2, lng2)
