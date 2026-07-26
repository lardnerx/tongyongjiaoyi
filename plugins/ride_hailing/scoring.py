"""网约车匹配评分工具。"""

from __future__ import annotations

import math
from typing import Any

from umcp_core.core.resource import Resource
from umcp_core.core.task import Task


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """haversine 公式计算两个经纬度之间的距离（公里）。

    地球半径取 6371 公里。
    """
    r = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class RideMatchScorer:
    """网约车匹配评分器。

    按司机当前位置到乘客起点的距离评分。
    返回负距离（-distance），使 InstantMatch 升序排列时近者排在前。
    """

    def __call__(self, task: Task, resource: Resource) -> float:
        if task.spatio_temporal is None:
            return 0.0
        if task.spatio_temporal.origin_lat is None or task.spatio_temporal.origin_lng is None:
            return 0.0
        driver_lat = resource.metadata.get("current_lat")
        driver_lng = resource.metadata.get("current_lng")
        if driver_lat is None or driver_lng is None:
            return 0.0
        distance = haversine_km(
            task.spatio_temporal.origin_lat,
            task.spatio_temporal.origin_lng,
            driver_lat,
            driver_lng,
        )
        return -distance
