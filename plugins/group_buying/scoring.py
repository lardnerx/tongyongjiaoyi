"""集采行业报价评分器。"""
from __future__ import annotations

from typing import Any

from umcp_core.core.resource import Resource
from umcp_core.core.task import Task
from umcp_core.layers.l3 import CompositeBidScorer


# 硬约束不满足时的极低分（与 InstantMatch/ReverseAuction 的 reverse=True 配合，会被排到末尾）
MISSING_REQUIREMENT_SCORE: float = -1.0


class TenderBidScorer:
    """集采行业报价评分器（行业策略）。

    组合通用 CompositeBidScorer 与集采特有逻辑：
    1. 资质硬约束：无 business_license 直接返回 -1.0
    2. 服务能力匹配：供应商必须覆盖招标要求的服务标签
    3. 通用报价评分（价格+交期+信誉加权）

    评分方向：降序优先（与 ReverseAuction 的 reverse=True 一致）。

    为何不放核心库：服务能力标签匹配是集采特有逻辑，其他行业
    （网约车/陪驾）无此概念。
    """

    def __init__(
        self,
        required_service_tags: list[str] | None = None,
        composite_scorer: CompositeBidScorer | None = None,
    ) -> None:
        self.required_service_tags: list[str] = required_service_tags or []
        self._composite_scorer: CompositeBidScorer = composite_scorer or CompositeBidScorer()

    def __call__(self, task: Task, resource: Resource) -> float:
        # 1. 资质硬约束
        if not resource.has_capability("business_license"):
            return MISSING_REQUIREMENT_SCORE

        # 2. 服务能力匹配（task 可动态指定 required_service_tags）
        required_tags = (
            task.custom_fields.get("required_service_tags")
            or self.required_service_tags
        )
        if required_tags:
            supplier_tags = set(resource.metadata.get("service_capability", []))
            if not set(required_tags).issubset(supplier_tags):
                return MISSING_REQUIREMENT_SCORE

        # 3. 通用报价评分
        return self._composite_scorer(task, resource)
