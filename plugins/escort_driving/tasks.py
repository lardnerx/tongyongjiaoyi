"""陪驾服务任务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.core.domain import DomainTag, SpatioTemporalConstraint
from umcp_core.core.task import StandardTask


class EscortTask(StandardTask):
    """陪驾服务任务（标准化任务）。

    封装集合点、车型需求、技能标签需求、预期时长等字段。
    实时模式下，actual_hours 默认等于 duration_hours，服务完成时可由调用方更新。
    """

    _task_type_name = "escort"

    def __init__(
        self,
        demander_id: str,
        origin_lat: float,
        origin_lng: float,
        domain_tag: DomainTag | None = None,
        car_type: str = "manual",
        required_skills: list[str] | None = None,
        duration_hours: float = 1.0,
        order_type: str = "REALTIME",
        scheduled_at: datetime | None = None,
        coach_level_pref: str = "ANY",
        origin_address: str | None = None,
        **kwargs: Any,
    ) -> None:
        if domain_tag is None:
            domain_tag = DomainTag.of("escort")
        spatio = SpatioTemporalConstraint(
            origin_lat=origin_lat,
            origin_lng=origin_lng,
        )
        super().__init__(demander_id, domain_tag, spatio_temporal=spatio, **kwargs)

        self.order_type = order_type
        self.scheduled_at = scheduled_at
        self.coach_level_pref = coach_level_pref

        self.structured_fields["car_type"] = car_type
        # 集合点坐标同时写入结构化字段：Task 仓储不持久化 spatio_temporal，
        # 仅靠内存对象会导致订单刷新后丢失坐标（前端无法计算距离/打点）。
        self.structured_fields["origin_lat"] = origin_lat
        self.structured_fields["origin_lng"] = origin_lng
        self.structured_fields["required_skills"] = required_skills or []
        self.structured_fields["duration_hours"] = duration_hours
        self.structured_fields["order_type"] = order_type
        self.structured_fields["scheduled_at"] = (
            scheduled_at.isoformat() if scheduled_at else None
        )
        self.structured_fields["coach_level_pref"] = coach_level_pref
        if origin_address:
            self.structured_fields["origin_address"] = origin_address

        # 供 Hourly 支付策略使用
        self.custom_fields["actual_hours"] = duration_hours

    def task_type(self) -> str:
        return "escort"
