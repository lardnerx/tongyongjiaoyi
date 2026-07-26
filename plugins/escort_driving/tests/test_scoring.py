"""测试陪驾行业匹配评分器。"""

from __future__ import annotations

from umcp_core.core import DomainTag
from escort_driving.resources import CoachResource
from escort_driving.scoring import EscortMatchScorer
from escort_driving.tasks import EscortTask


class TestEscortMatchScorer:
    def test_full_skill_overlap_with_a_level_coach_scores_highest(self):
        """A 级教练且技能全匹配应得最高分。"""
        scorer = EscortMatchScorer()
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="manual",
            required_skills=["highway", "night", "parking"],
        )
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="A",
            skills=["highway", "night", "parking"],
        )
        # 3 个技能匹配 + A 级加权 1.0 = 4.0
        assert scorer(task, coach) == 4.0

    def test_partial_skill_overlap_with_b_level_coach(self):
        """B 级教练部分技能匹配。"""
        scorer = EscortMatchScorer()
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="manual",
            required_skills=["highway", "night", "parking"],
        )
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="B",
            skills=["highway", "parking"],  # 交集 2
        )
        # 2 个技能匹配 + B 级加权 0.0 = 2.0
        assert scorer(task, coach) == 2.0

    def test_car_type_mismatch_returns_negative_score(self):
        """车型不匹配时返回 -1.0（极低分，硬性约束）。"""
        scorer = EscortMatchScorer()
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="automatic",
            required_skills=["highway"],
        )
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",  # 不匹配
            coach_level="A",
            skills=["highway"],
        )
        assert scorer(task, coach) == -1.0

    def test_a_level_coach_scores_higher_than_b_level_with_same_skills(self):
        """技能相同时，A 级教练评分应高于 B 级。"""
        scorer = EscortMatchScorer()
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="manual",
            required_skills=["highway"],
        )
        coach_a = CoachResource(
            supplier_id="s_a",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="A",
            skills=["highway"],
        )
        coach_b = CoachResource(
            supplier_id="s_b",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="B",
            skills=["highway"],
        )
        assert scorer(task, coach_a) > scorer(task, coach_b)

    def test_more_skills_match_scores_higher(self):
        """技能匹配更多的教练评分应更高。"""
        scorer = EscortMatchScorer()
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="manual",
            required_skills=["highway", "night", "parking"],
        )
        better_coach = CoachResource(
            supplier_id="s_better",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="B",
            skills=["highway", "night", "parking"],  # 交集 3
        )
        worse_coach = CoachResource(
            supplier_id="s_worse",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="B",
            skills=["highway"],  # 交集 1
        )
        assert scorer(task, better_coach) > scorer(task, worse_coach)

    def test_no_required_skills_returns_level_weight_only(self):
        """学员无技能需求时，仅按教练等级评分。"""
        scorer = EscortMatchScorer()
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="manual",
            required_skills=[],  # 无需求
        )
        coach_a = CoachResource(
            supplier_id="s_a",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="A",
            skills=["highway"],
        )
        # 0 个技能匹配 + A 级加权 1.0 = 1.0
        assert scorer(task, coach_a) == 1.0

    def test_car_type_mismatch_overrides_skill_match(self):
        """车型不匹配时，即使技能全匹配也返回 -1.0。"""
        scorer = EscortMatchScorer()
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="automatic",
            required_skills=["highway", "night"],
        )
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",  # 不匹配
            coach_level="A",
            skills=["highway", "night"],  # 全匹配
        )
        assert scorer(task, coach) == -1.0
