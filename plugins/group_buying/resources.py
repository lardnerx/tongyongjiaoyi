"""集采服务供应商资源。"""
from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource


class SupplierResource(Resource):
    """供应商资源（可投标单元）。

    代表供应商+商品SKU+服务能力的组合。
    默认具备 business_license 能力（准入规则要求）。
    """

    def __init__(
        self,
        supplier_id: str,
        domain_tag: DomainTag,
        supplier_name: str,
        product_sku: str,
        service_capability: list[str] | None = None,
        trust_score: float = 3.0,
        capabilities: list[Capability] | None = None,
        **kwargs: Any,
    ) -> None:
        if capabilities is None:
            capabilities = [
                Capability(
                    type="certification",
                    name="business_license",
                    value="registered",
                    verified=True,
                ),
            ]
        super().__init__(
            supplier_id,
            domain_tag,
            capabilities=capabilities,
            **kwargs,
        )
        self.metadata["supplier_name"] = supplier_name
        self.metadata["product_sku"] = product_sku
        self.metadata["service_capability"] = service_capability or []
        self.metadata["trust_score"] = trust_score

    def resource_type(self) -> str:
        return "supplier"
