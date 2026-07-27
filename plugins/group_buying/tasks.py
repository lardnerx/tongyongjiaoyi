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


class TenderTask(PackageTask):
    """聚合招标任务（混合任务）。

    虚拟中间人聚合多个 BuyerTask 后发起的招标任务。
    包含 1 个商品子任务（StandardTask）+ 1 个服务子任务（CustomTask）。
    完成前置校验：所有子任务必须 COMPLETED 才能调 complete()。
    """

    _task_type_name = "tender"

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        category: str,
        total_quantity: int,
        target_unit_price: float,
        buyer_task_ids: list[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(demander_id, domain_tag, **kwargs)
        self.custom_fields["category"] = category
        self.custom_fields["total_quantity"] = total_quantity
        self.custom_fields["target_unit_price"] = target_unit_price
        self.custom_fields["buyer_task_ids"] = list(buyer_task_ids)

    def task_type(self) -> str:
        return "tender"

    def complete(self) -> None:
        """完成招标任务，前置校验所有子任务必须已完成。"""
        for sub in self.standard_sub_tasks:
            if sub.status != TaskStatus.COMPLETED:
                raise RuntimeError(f"子任务 {sub.task_id} 未完成")
        if self.custom_sub_task and self.custom_sub_task.status != TaskStatus.COMPLETED:
            raise RuntimeError("服务子任务未完成")
        super().complete()
