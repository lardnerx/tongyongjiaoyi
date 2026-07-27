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

    当传入 scorer 时，execute() 会按 scorer 降序自动选最高分资源
    （与 InstantMatch 行为一致）。无 scorer 时仅返回候选列表。
    """

    def __init__(
        self,
        mode: str = "reverse_auction",
        filters: list[PreMatchFilter] | None = None,
        scorer: Any = None,
    ) -> None:
        if mode not in ("reverse_auction", "proposal_bid"):
            raise ValueError(f"未知招标模式: {mode}")
        self.mode: str = mode
        self.filters: list[PreMatchFilter] = filters or []
        self.scorer = scorer  # callable(task, resource) -> float

    def execute(self, task: Task, candidates: list[Resource]) -> MatchResult:
        filtered = self.apply_filters(task, candidates, self.filters)
        if not filtered:
            # 无候选：返回空结果但保留 mode 元信息（与原行为一致）
            return MatchResult(
                task_id=task.task_id,
                selected_resource_id=None,
                candidates=[],
                metadata={"mode": self.mode, "awaiting_proposals": True},
            )

        if self.scorer is not None:
            # 有 scorer：按评分降序选最高分（与 InstantMatch 一致）
            filtered.sort(key=lambda r: self.scorer(task, r), reverse=True)
            selected = filtered[0]
            return MatchResult(
                task_id=task.task_id,
                selected_resource_id=selected.resource_id,
                candidates=[r.resource_id for r in filtered],
                metadata={"mode": self.mode, "auto_selected": True},
            )

        # 无 scorer：返回候选，由上层业务流程选标
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=None,
            candidates=[r.resource_id for r in filtered],
            metadata={"mode": self.mode, "awaiting_proposals": True},
        )


class ReverseAuction(Bidding):
    """逆向拍卖：供给方出价，需求方选最低价或最优综合评分。

    传入 scorer 时自动选最高分；不传时仅返回候选。
    """

    def __init__(
        self,
        filters: list[PreMatchFilter] | None = None,
        scorer: Any = None,
    ) -> None:
        super().__init__(mode="reverse_auction", filters=filters, scorer=scorer)


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


class SkillMatchScorer:
    """技能匹配评分器（预置通用）。

    基于 Task.required_skills 与 Resource.skills 的标签交集数量评分。
    交集越大评分越高，配合 InstantMatch 的 reverse=True 实现高分优先。

    通用性：任何需要技能标签匹配的场景（陪驾、家教、家政、维修）都可复用。
    """

    def __call__(self, task: Task, resource: Resource) -> float:
        required = task.structured_fields.get("required_skills", [])
        if not required:
            return 0.0
        skills = resource.metadata.get("skills", [])
        if not skills:
            return 0.0
        intersection = set(required) & set(skills)
        return float(len(intersection))


class CompositeBidScorer:
    """通用多维度报价评分器（预置）。

    基于 resource.metadata["bid"] 的价格、交期、信誉三维度加权评分。
    价格越低分越高，交期越短分越高，信誉越高分越高。
    与 ReverseAuction 的 scorer 配合实现高分优先。

    归一化基准：从 task.custom_fields["bid_price_range"] 和
    task.custom_fields["bid_delivery_range"] 读取 (min, max) 元组。
    单 bid 场景（min == max）时价格分和交期分均为 1.0（中性满分）。

    通用性：任何需要多维度报价评分的招标场景（集采、外包、咨询）都可复用。
    """

    def __init__(
        self,
        price_weight: float = 0.5,
        delivery_weight: float = 0.3,
        trust_weight: float = 0.2,
    ) -> None:
        self.price_weight: float = price_weight
        self.delivery_weight: float = delivery_weight
        self.trust_weight: float = trust_weight

    def __call__(self, task: Task, resource: Resource) -> float:
        bid = resource.metadata.get("bid")
        if not bid:
            return 0.0

        price = float(bid.get("price", 0.0))
        delivery_days = float(bid.get("delivery_days", 0.0))
        trust_score = float(resource.metadata.get("trust_score", 0.0))

        price_range = task.custom_fields.get("bid_price_range", (price, price))
        delivery_range = task.custom_fields.get("bid_delivery_range", (delivery_days, delivery_days))

        price_min, price_max = price_range
        delivery_min, delivery_max = delivery_range

        # 价格分：越低越高。max == min 时返回 1.0（无对比基准）
        if price_max == price_min:
            price_score = 1.0
        else:
            price_score = (price_max - price) / (price_max - price_min)

        # 交期分：越短越高
        if delivery_max == delivery_min:
            delivery_score = 1.0
        else:
            delivery_score = (delivery_max - delivery_days) / (delivery_max - delivery_min)

        # 信誉分：满分 5.0
        trust_score_normalized = trust_score / 5.0

        total = (
            price_score * self.price_weight
            + delivery_score * self.delivery_weight
            + trust_score_normalized * self.trust_weight
        )
        return round(total, 6)

