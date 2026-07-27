"""集采服务任务：BuyerTask（采购需求意向）+ TenderTask（聚合招标）。"""
from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import CustomTask, PackageTask, TaskStatus, StandardTask


class BuyerTask(CustomTask):
    """采购需求意向（非标准化任务）。

    单个小微单位的采购需求，作为聚合原料。
    继承 CustomTask，携带预算范围。
    """

    _task_type_name = "buyer"

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        category: str,
        quantity: int,
        budget_max: float,
        spec_requirements: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(demander_id, domain_tag, budget_max=budget_max, **kwargs)
        self.custom_fields["category"] = category
        self.custom_fields["quantity"] = quantity
        self.custom_fields["spec_requirements"] = spec_requirements or []

    def task_type(self) -> str:
        return "buyer"


# TenderTask 将在任务 5 添加
