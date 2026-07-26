"""L3 匹配与调度层：匹配策略、预过滤管道、匹配结果。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from umcp_core.core.resource import Resource
from umcp_core.core.task import Task


@dataclass
class MatchResult:
    """匹配结果。"""

    task_id: str
    selected_resource_id: str | None = None
    bid_amount: float | None = None
    candidates: list[str] = field(default_factory=list)  # 候选资源 ID 列表
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        return self.selected_resource_id is not None


class PreMatchFilter(ABC):
    """预匹配过滤器接口（责任链模式）。"""

    @abstractmethod
    def filter(self, task: Task, resource: Resource) -> bool:
        """返回 True 表示资源通过过滤，False 表示被排除。"""


class CredentialFilter(PreMatchFilter):
    """资质过滤器：检查资源是否具备任务要求的资质。"""

    def __init__(self, required_credentials: list[str] | None = None) -> None:
        self.required_credentials: list[str] = required_credentials or []

    def filter(self, task: Task, resource: Resource) -> bool:
        for cred_name in self.required_credentials:
            if not resource.has_capability(cred_name):
                return False
        return True


class TrustThresholdFilter(PreMatchFilter):
    """信任门槛过滤器：根据资源信用分过滤。"""

    def __init__(self, threshold: float = 0.0, trust_lookup: Any = None) -> None:
        self.threshold: float = threshold
        self.trust_lookup = trust_lookup  # callable(user_id) -> float

    def filter(self, task: Task, resource: Resource) -> bool:
        if self.trust_lookup is None:
            return True
        try:
            score = self.trust_lookup(resource.supplier_id)
            return score >= self.threshold
        except Exception:
            return False


class CapabilityFilter(PreMatchFilter):
    """能力过滤器：检查资源是否具备任务要求的能力。"""

    def filter(self, task: Task, resource: Resource) -> bool:
        required = task.custom_fields.get("required_capabilities", [])
        if not required:
            return True
        for cap_name in required:
            if not resource.has_capability(cap_name):
                return False
        return True


class MatchStrategy(ABC):
    """匹配策略接口。"""

    @abstractmethod
    def execute(self, task: Task, candidates: list[Resource]) -> MatchResult:
        """对任务执行匹配，从候选资源中选出最佳匹配。"""

    def apply_filters(
        self,
        task: Task,
        candidates: list[Resource],
        filters: list[PreMatchFilter] | None = None,
    ) -> list[Resource]:
        """应用预过滤管道。"""
        if not filters:
            return list(candidates)
        result: list[Resource] = []
        for res in candidates:
            if all(f.filter(task, res) for f in filters):
                result.append(res)
        return result


class InstantMatch(MatchStrategy):
    """系统派单策略（预置）。

    基于规则自动选择最优资源，用于标准化任务（打车、配送等）。
    有 scorer 时按 scorer 返回值降序排列（高分优先，如负距离近者更接近 0 更大）；
    无 scorer 时按资源更新时间降序排列（最近活跃优先）。
    """

    def __init__(
        self,
        filters: list[PreMatchFilter] | None = None,
        scorer: Any = None,
    ) -> None:
        self.filters: list[PreMatchFilter] = filters or []
        self.scorer = scorer  # callable(task, resource) -> float

    def execute(self, task: Task, candidates: list[Resource]) -> MatchResult:
        filtered = self.apply_filters(task, candidates, self.filters)
        if not filtered:
            return MatchResult(task_id=task.task_id)

        if self.scorer is not None:
            # scorer 返回值越大表示越匹配（如负距离：近者返回值更接近 0，更大）
            filtered.sort(key=lambda r: self.scorer(task, r), reverse=True)
        else:
            # 默认：按资源更新时间排序（最近活跃优先）
            filtered.sort(key=lambda r: r.updated_at, reverse=True)

        selected = filtered[0]
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=selected.resource_id,
            candidates=[r.resource_id for r in filtered],
        )


class DirectPick(MatchStrategy):
    """需方自选策略（预置）。

    返回所有候选资源，由需求方手动选择。
    """

    def __init__(self, filters: list[PreMatchFilter] | None = None) -> None:
        self.filters: list[PreMatchFilter] = filters or []

    def execute(self, task: Task, candidates: list[Resource]) -> MatchResult:
        filtered = self.apply_filters(task, candidates, self.filters)
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=None,
            candidates=[r.resource_id for r in filtered],
        )


class Bidding(MatchStrategy):
    """招标策略（预置）。

    用于非标准化任务。支持两种变体：
    - ReverseAuction：供给方出价，需求方选最低价或最优信誉
    - ProposalBid：供给方提交方案，需求方选标
    """

    def __init__(
        self,
        mode: str = "reverse_auction",
        filters: list[PreMatchFilter] | None = None,
    ) -> None:
        if mode not in ("reverse_auction", "proposal_bid"):
            raise ValueError(f"未知招标模式: {mode}")
        self.mode: str = mode
        self.filters: list[PreMatchFilter] = filters or []

    def execute(self, task: Task, candidates: list[Resource]) -> MatchResult:
        filtered = self.apply_filters(task, candidates, self.filters)
        # 实际的报价收集与选标由上层业务流程驱动，此处仅返回候选
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=None,
            candidates=[r.resource_id for r in filtered],
            metadata={"mode": self.mode, "awaiting_proposals": True},
        )


class ReverseAuction(Bidding):
    """逆向拍卖：供给方出价，需求方选最低价。"""

    def __init__(self, filters: list[PreMatchFilter] | None = None) -> None:
        super().__init__(mode="reverse_auction", filters=filters)


class ProposalBid(Bidding):
    """方案竞标：供给方提交方案，需求方选标。"""

    def __init__(self, filters: list[PreMatchFilter] | None = None) -> None:
        super().__init__(mode="proposal_bid", filters=filters)


# ============================================================================
# 兼容 CodeWiki 9.2 命名（与 4.4 节预置策略等价，详见 CodeWiki.md 9.2.3 命名对照脚注）
# ============================================================================


class NearestMatch(InstantMatch):
    """NearestMatch ≈ InstantMatch（系统按距离/可用性自动派单）。

    此别名仅为与 CodeWiki 9.2 节工程实施方案的命名保持兼容，行为与 InstantMatch 一致。
    实际编码建议直接使用 InstantMatch。
    """


class AuctionMatch(Bidding):
    """AuctionMatch ≈ Bidding（供给方出价、需求方选标）。

    此别名仅为与 CodeWiki 9.2 节工程实施方案的命名保持兼容，行为与 Bidding 一致。
    实际编码建议直接使用 Bidding。
    """

