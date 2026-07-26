"""陪驾教练资源。"""

from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource


class CoachResource(Resource):
    """教练资源（可调度单元）。

    封装当前位置、车牌、车型、教练等级、技能标签等字段。
    默认具备 coach_license 能力（准入规则要求）。
    """

    def __init__(
        self,
        supplier_id: str,
        domain_tag: DomainTag,
        current_lat: float,
        current_lng: float,
        car_type: str = "manual",
        coach_level: str = "B",
        skills: list[str] | None = None,
        plate_number: str = "",
        capabilities: list[Capability] | None = None,
        **kwargs: Any,
    ) -> None:
        if capabilities is None:
            capabilities = [
                Capability(
                    type="certification",
                    name="coach_license",
                    value="A1",
                    verified=True,
                ),
            ]
        super().__init__(
            supplier_id,
            domain_tag,
            capabilities=capabilities,
            **kwargs,
        )
        self.metadata["current_lat"] = current_lat
        self.metadata["current_lng"] = current_lng
        self.metadata["car_type"] = car_type
        self.metadata["coach_level"] = coach_level
        self.metadata["skills"] = skills or []
        self.metadata["plate_number"] = plate_number

    def resource_type(self) -> str:
        return "coach"
