"""测试通用技能匹配评分器。"""

from __future__ import annotations

from umcp_core.core import DomainTag
from umcp_core.core.resource import Resource
from umcp_core.core.task import StandardTask
from umcp_core.layers.l3 import SkillMatchScorer


class TestSkillMatchScorer:
    def test_full_skill_overlap_returns_high_score(self):
        """学员需求技能全部被教练覆盖时，评分应为需求技能数。"""
        scorer = SkillMatchScorer()

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        task = _Task(demander_id="u1", domain_tag=DomainTag.of("escort"))
        task.structured_fields["required_skills"] = ["highway", "night", "parking"]

        class _Coach(Resource):
            def resource_type(self) -> str:
                return "coach"

        coach = _Coach(supplier_id="s1", domain_tag=DomainTag.of("escort"))
        coach.metadata["skills"] = ["highway", "night", "parking", "manual"]

        assert scorer(task, coach) == 3.0

    def test_partial_overlap_returns_intersection_count(self):
        """部分重叠时返回交集数量。"""
        scorer = SkillMatchScorer()

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        task = _Task(demander_id="u1", domain_tag=DomainTag.of("escort"))
        task.structured_fields["required_skills"] = ["highway", "night", "parking"]

        class _Coach(Resource):
            def resource_type(self) -> str:
                return "coach"

        coach = _Coach(supplier_id="s1", domain_tag=DomainTag.of("escort"))
        coach.metadata["skills"] = ["highway", "parking"]  # 交集 2 个

        assert scorer(task, coach) == 2.0

    def test_no_overlap_returns_zero(self):
        """无交集时返回 0。"""
        scorer = SkillMatchScorer()

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        task = _Task(demander_id="u1", domain_tag=DomainTag.of("escort"))
        task.structured_fields["required_skills"] = ["highway"]

        class _Coach(Resource):
            def resource_type(self) -> str:
                return "coach"

        coach = _Coach(supplier_id="s1", domain_tag=DomainTag.of("escort"))
        coach.metadata["skills"] = ["night", "parking"]

        assert scorer(task, coach) == 0.0

    def test_task_without_required_skills_returns_zero(self):
        """任务未声明 required_skills 时返回 0（中性评分）。"""
        scorer = SkillMatchScorer()

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        task = _Task(demander_id="u1", domain_tag=DomainTag.of("escort"))
        # 不设置 required_skills

        class _Coach(Resource):
            def resource_type(self) -> str:
                return "coach"

        coach = _Coach(supplier_id="s1", domain_tag=DomainTag.of("escort"))
        coach.metadata["skills"] = ["highway"]

        assert scorer(task, coach) == 0.0

    def test_coach_without_skills_returns_zero(self):
        """教练未声明 skills 时返回 0。"""
        scorer = SkillMatchScorer()

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        task = _Task(demander_id="u1", domain_tag=DomainTag.of("escort"))
        task.structured_fields["required_skills"] = ["highway"]

        class _Coach(Resource):
            def resource_type(self) -> str:
                return "coach"

        coach = _Coach(supplier_id="s1", domain_tag=DomainTag.of("escort"))
        # 不设置 skills

        assert scorer(task, coach) == 0.0

    def test_higher_score_means_better_match(self):
        """技能覆盖更多的教练评分应更高（用于 InstantMatch 降序排序）。"""
        scorer = SkillMatchScorer()

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        task = _Task(demander_id="u1", domain_tag=DomainTag.of("escort"))
        task.structured_fields["required_skills"] = ["highway", "night", "parking"]

        class _Coach(Resource):
            def resource_type(self) -> str:
                return "coach"

        better_coach = _Coach(supplier_id="s_better", domain_tag=DomainTag.of("escort"))
        better_coach.metadata["skills"] = ["highway", "night", "parking"]  # 交集 3

        worse_coach = _Coach(supplier_id="s_worse", domain_tag=DomainTag.of("escort"))
        worse_coach.metadata["skills"] = ["highway"]  # 交集 1

        assert scorer(task, better_coach) > scorer(task, worse_coach)
