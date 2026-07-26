"""网约车行程任务。"""

from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag, SpatioTemporalConstraint
from umcp_core.core.task import StandardTask
from ride_hailing.scoring import haversine_km


class RideTask(StandardTask):
    """网约车行程任务（标准化任务）。

    封装起终点、车型、乘客数、预估价等字段。
    距离基于起终点自动计算，预估价基于距离 + 车型。
    """

    _task_type_name = "ride"

    BASE_RATE_PER_KM = 2.5  # 每公里基础费率（元）

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        car_type: str = "economy",
        passenger_count: int = 1,
        **kwargs: Any,
    ) -> None:
        spatio = SpatioTemporalConstraint(
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
        )
        super().__init__(demander_id, domain_tag, spatio_temporal=spatio, **kwargs)

        distance_km = haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
        base_price = round(distance_km * self.BASE_RATE_PER_KM, 2)

        self.structured_fields["car_type"] = car_type
        self.structured_fields["passenger_count"] = passenger_count
        self.structured_fields["estimated_distance_km"] = round(distance_km, 2)

        self.custom_fields["base_price"] = base_price
        self.custom_fields["price"] = base_price

    def task_type(self) -> str:
        return "ride"
