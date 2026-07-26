"""网约车司机资源。"""

from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource


class DriverResource(Resource):
    """司机资源（可调度单元）。

    封装当前位置、车牌、车型等字段。
    默认具备 driver_license 能力（准入规则要求）。
    """

    def __init__(
        self,
        supplier_id: str,
        domain_tag: DomainTag,
        current_lat: float,
        current_lng: float,
        car_type: str = "economy",
        plate_number: str = "",
        capabilities: list[Capability] | None = None,
        **kwargs: Any,
    ) -> None:
        if capabilities is None:
            capabilities = [
                Capability(
                    type="certification",
                    name="driver_license",
                    value="C1",
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
        self.metadata["plate_number"] = plate_number

    def resource_type(self) -> str:
        return "driver"
