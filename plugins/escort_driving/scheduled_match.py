"""预约单 Top N 推荐匹配策略。"""
from __future__ import annotations

from plugins.escort_driving.scoring import CAR_TYPE_MISMATCH_SCORE, EscortMatchScorer
from umcp_core.layers.l3 import MatchResult, MatchStrategy


class ScheduledMatchStrategy(MatchStrategy):
    """预约单 Top N 推荐策略。

    与实时单 InstantMatch 不同，预约单不自动选定教练，
    而是返回 Top N 候选教练供学员选择。
    """

    def __init__(self, top_n: int = 3) -> None:
        self._scorer = EscortMatchScorer()
        self._top_n = top_n

    def execute(self, task, candidates: list) -> MatchResult:
        task_level_pref = task.structured_fields.get("coach_level_pref", "ANY")
        scored = []
        for resource in candidates:
            score = self._scorer(task, resource)
            # 车型不匹配直接跳过
            if score == CAR_TYPE_MISMATCH_SCORE:
                continue
            # 等级偏好过滤（ANY 时跳过过滤）
            if task_level_pref != "ANY":
                if resource.metadata.get("coach_level") != task_level_pref:
                    continue
            scored.append((resource, score))
        # 降序排序（高分优先）
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: self._top_n]
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=None,  # 预约单不自动选定
            candidates=[r.resource_id for r, _ in top],
        )
