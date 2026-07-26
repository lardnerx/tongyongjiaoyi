"""陪驾服务任务。"""

from __future__ import annotations

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
        domain_tag: DomainTag,
        origin_lat: float,
        origin_lng: float,
        car_type: str = "manual",
        required_skills: list[str] | None = None,
        duration_hours: float = 1.0,
        **kwargs: Any,
    ) -> None:
        spatio = SpatioTemporalConstraint(
            origin_lat=origin_lat,
            origin_lng=origin_lng,
        )
        super().__init__(demander_id, domain_tag, spatio_temporal=spatio, **kwargs)

        self.structured_fields["car_type"] = car_type
        self.structured_fields["required_skills"] = required_skills or []
        self.structured_fields["duration_hours"] = duration_hours

        # 供 Hourly 支付策略使用
        self.custom_fields["actual_hours"] = duration_hours

    def task_type(self) -> str:
        return "escort"
