"""陪驾行业匹配评分器。"""

from __future__ import annotations

from umcp_core.core.resource import Resource
from umcp_core.core.task import Task
from umcp_core.layers.l3 import SkillMatchScorer


# 教练等级加权映射（A 级优于 B 级）
COACH_LEVEL_WEIGHT: dict[str, float] = {
    "A": 1.0,
    "B": 0.0,
}

# 车型不匹配时的惩罚分（确保降序排序时排到最后）
CAR_TYPE_MISMATCH_SCORE: float = -1.0


class EscortMatchScorer:
    """陪驾行业匹配评分器（行业策略）。

    组合通用 SkillMatchScorer 与陪驾特有逻辑：
    1. 车型必须匹配（硬性约束）：不匹配返回 -1.0
    2. 技能匹配分（调用通用 SkillMatchScorer）
    3. 教练等级加权（A 级 +1.0，B 级 +0.0）

    综合评分 = 技能匹配分 + 等级加权（车型不匹配则 -1.0）

    评分方向：降序优先（与 InstantMatch 的 reverse=True 一致）。

    为何不放核心库：教练等级加权是陪驾特有逻辑，其他行业（家教、家政）
    有不同的等级体系，无法通用。
    """

    def __init__(self) -> None:
        self._skill_scorer: SkillMatchScorer = SkillMatchScorer()

    def __call__(self, task: Task, resource: Resource) -> float:
        task_car_type = task.structured_fields.get("car_type")
        coach_car_type = resource.metadata.get("car_type")

        # 硬性约束：车型必须匹配
        if task_car_type != coach_car_type:
            return CAR_TYPE_MISMATCH_SCORE

        # 技能匹配分
        skill_score = self._skill_scorer(task, resource)

        # 教练等级加权
        coach_level = resource.metadata.get("coach_level", "B")
        level_weight = COACH_LEVEL_WEIGHT.get(coach_level, 0.0)

        return skill_score + level_weight
