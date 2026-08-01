"""LBS 服务抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LocationInfo:
    """资源位置信息。"""

    resource_id: str
    lat: float
    lng: float
    heading: float = 0.0
    speed: float = 0.0
    updated_at: Any = None  # datetime，避免导入


class LBSService(ABC):
    """LBS 服务抽象基类。"""

    @abstractmethod
    def update_location(
        self, resource_id: str, lat: float, lng: float, heading: float = 0.0, speed: float = 0.0
    ) -> None:
        """更新资源位置。"""

    @abstractmethod
    def get_location(self, resource_id: str) -> dict[str, Any] | None:
        """查询资源最新位置。"""

    @abstractmethod
    def nearby(
        self, lat: float, lng: float, radius_km: float, level: str | None = None
    ) -> list[dict[str, Any]]:
        """查询附近资源，返回按距离升序排列的列表。"""

    @abstractmethod
    def distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """计算两点间距离（公里）。"""
