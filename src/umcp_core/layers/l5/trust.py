"""L5 信任与信用层：评价、信用画像、资质、风险权重。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from umcp_core.core.domain import Credential
from umcp_core.core.task import Task


@dataclass
class Evaluation:
    """评价记录。"""

    evaluator_id: str
    evaluatee_id: str
    task_id: str
    ratings: dict[str, float] = field(default_factory=dict)  # 维度 -> 分数
    comment: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TrustProfile:
    """多维信誉画像。

    信用不能是单一分数，必须是多维画像。
    """

    user_id: str
    dimension_scores: dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def update_dimension(self, dimension: str, score: float) -> None:
        self.dimension_scores[dimension] = score
        if self.dimension_scores:
            self.overall_score = sum(self.dimension_scores.values()) / len(self.dimension_scores)
        self.last_updated = datetime.utcnow()

    def get_score(self, dimension: str | None = None) -> float:
        if dimension is None:
            return self.overall_score
        return self.dimension_scores.get(dimension, 0.0)


@dataclass
class RiskWeight:
    """行业化风险权重。"""

    weights: dict[str, float] = field(default_factory=dict)

    def weight_of(self, dimension: str) -> float:
        return self.weights.get(dimension, 1.0)


class CredentialValidator(ABC):
    """资质验证器接口。"""

    @abstractmethod
    def validate(self, credential: Credential) -> bool:
        """验证资质是否有效。"""


class SimpleCredentialValidator(CredentialValidator):
    """简单资质验证器（默认实现）。"""

    def validate(self, credential: Credential) -> bool:
        # 默认实现：仅检查 token 非空
        return bool(credential.token)


class TrustEngine(ABC):
    """信任引擎接口。

    L5 不是终点，是下一次匹配的起点 —— 持续运行的信任引擎。
    """

    @abstractmethod
    def evaluate(self, user_id: str, context: Task | None = None) -> TrustProfile:
        """评估用户的多维信誉画像。"""

    @abstractmethod
    def record_evaluation(self, evaluation: Evaluation) -> TrustProfile:
        """记录评价并更新画像。"""


class WeightedSumTrustEngine(TrustEngine):
    """加权聚合信任引擎（核心库默认实现）。

    评价维度和风险权重通过配置注入。
    """

    def __init__(
        self,
        dimensions: list[str] | None = None,
        risk_weight: RiskWeight | None = None,
    ) -> None:
        self.dimensions: list[str] = dimensions or ["overall"]
        self.risk_weight: RiskWeight = risk_weight or RiskWeight()
        self._profiles: dict[str, TrustProfile] = {}

    def evaluate(self, user_id: str, context: Task | None = None) -> TrustProfile:
        if user_id not in self._profiles:
            self._profiles[user_id] = TrustProfile(user_id=user_id)
            for dim in self.dimensions:
                self._profiles[user_id].update_dimension(dim, 0.0)
        return self._profiles[user_id]

    def record_evaluation(self, evaluation: Evaluation) -> TrustProfile:
        profile = self.evaluate(evaluation.evaluatee_id)
        for dim, score in evaluation.ratings.items():
            current = profile.dimension_scores.get(dim, 0.0)
            # 简单移动平均：新旧各占 50%
            new_score = (current + score) / 2 if current > 0 else score
            profile.update_dimension(dim, new_score)
        return profile


# ============================================================================
# 兼容 CodeWiki 9.2 命名（与 10.1 节核心类图等价，详见 CodeWiki.md 9.2.4 命名对照脚注）
# ============================================================================


class SimpleRating(WeightedSumTrustEngine):
    """SimpleRating ≈ RatingAggregator（大众服务的简单评分聚合）。

    此别名仅为与 CodeWiki 10.1 节核心类图命名保持兼容，行为与 WeightedSumTrustEngine 一致。
    实际编码建议直接使用 WeightedSumTrustEngine。
    """


class CredibilityScore(WeightedSumTrustEngine):
    """CredibilityScore ≈ CredibilityModel（专业服务的多因子信誉模型）。

    此别名仅为与 CodeWiki 10.1 节核心类图命名保持兼容，行为与 WeightedSumTrustEngine 一致。
    实际编码建议直接使用 WeightedSumTrustEngine 并配置多因子维度。
    """


class SkillBadge:
    """SkillBadge ≈ BadgeSystem（徽章体系）。

    授予"快速响应"、"金牌设计师"等徽章。
    """

    def __init__(self) -> None:
        self._badges: dict[str, set[str]] = {}  # user_id -> {badge_name, ...}

    def grant(self, user_id: str, badge: str) -> None:
        self._badges.setdefault(user_id, set()).add(badge)

    def revoke(self, user_id: str, badge: str) -> None:
        if user_id in self._badges:
            self._badges[user_id].discard(badge)

    def list_badges(self, user_id: str) -> list[str]:
        return list(self._badges.get(user_id, set()))


# 9.2 命名兼容别名
RatingAggregator = SimpleRating
CredibilityModel = CredibilityScore
BadgeSystem = SkillBadge


class TrustAggregator(ABC):
    """跨 domain 信任聚合策略接口。

    用于跨 domain 聚合同一用户的 trust_score。
    默认实现为 MeanTrustAggregator（算术平均），行业应用可注入
    自定义实现（如交易量加权平均、取最低分等）。
    """

    @abstractmethod
    def aggregate(
        self,
        user_id: str,
        engines: dict[str, TrustEngine],
    ) -> float:
        """跨 domain 聚合 trust_score。

        Args:
            user_id: 用户 ID
            engines: domain → TrustEngine 映射（只含已注册的 domain）

        Returns:
            聚合后的 trust_score（0.0-5.0）
        """


class MeanTrustAggregator(TrustAggregator):
    """算术平均聚合策略（默认实现）。

    对每个 domain 的 TrustEngine.evaluate(user_id).overall_score
    取算术平均。未注册任何 engine 时返回 0.0。

    注意：未在某 engine 中留过评价记录的用户，evaluate() 会返回
    overall_score=0.0 的空 profile，仍纳入平均（这通常是期望行为：
    新用户从 0 分起步）。
    """

    def aggregate(
        self,
        user_id: str,
        engines: dict[str, TrustEngine],
    ) -> float:
        if not engines:
            return 0.0
        scores = [
            engine.evaluate(user_id).overall_score
            for engine in engines.values()
        ]
        return sum(scores) / len(scores)
