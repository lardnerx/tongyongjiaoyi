"""测试 L5 信任与信用层。"""

from __future__ import annotations

from umcp_core.core import DomainTag, StandardTask
from umcp_core.layers.l5 import (
    Evaluation,
    RiskWeight,
    SimpleCredentialValidator,
    SkillBadge,
    TrustProfile,
    WeightedSumTrustEngine,
)
from umcp_core.core.domain import Credential


class _Task(StandardTask):
    def task_type(self) -> str:
        return "test"


class TestTrustProfile:
    def test_update_dimension_updates_overall(self):
        profile = TrustProfile(user_id="u1")
        profile.update_dimension("punctuality", 4.5)
        assert profile.overall_score == 4.5

        profile.update_dimension("cleanliness", 3.5)
        assert profile.overall_score == 4.0  # (4.5 + 3.5) / 2

    def test_get_score_by_dimension(self):
        profile = TrustProfile(user_id="u1")
        profile.update_dimension("punctuality", 4.8)
        assert profile.get_score("punctuality") == 4.8
        assert profile.get_score("unknown") == 0.0
        assert profile.get_score() == 4.8


class TestWeightedSumTrustEngine:
    def test_evaluate_new_user_returns_empty_profile(self):
        engine = WeightedSumTrustEngine(dimensions=["punctuality", "cleanliness"])
        profile = engine.evaluate("u1")
        assert profile.user_id == "u1"
        assert "punctuality" in profile.dimension_scores
        assert "cleanliness" in profile.dimension_scores

    def test_record_evaluation_updates_profile(self):
        engine = WeightedSumTrustEngine(dimensions=["punctuality"])
        evaluation = Evaluation(
            evaluator_id="d1",
            evaluatee_id="s1",
            task_id="t1",
            ratings={"punctuality": 5.0},
        )
        profile = engine.record_evaluation(evaluation)
        assert profile.get_score("punctuality") == 5.0

        # 第二次评价，移动平均
        evaluation2 = Evaluation(
            evaluator_id="d2",
            evaluatee_id="s1",
            task_id="t2",
            ratings={"punctuality": 3.0},
        )
        profile = engine.record_evaluation(evaluation2)
        assert profile.get_score("punctuality") == 4.0  # (5 + 3) / 2


class TestCredentialValidator:
    def test_simple_validator_with_token(self):
        validator = SimpleCredentialValidator()
        assert validator.validate(Credential(type="phone", token="13800000000"))
        assert not validator.validate(Credential(type="phone", token=""))


class TestSkillBadge:
    def test_grant_and_list(self):
        badge_system = SkillBadge()
        badge_system.grant("u1", "fast_response")
        badge_system.grant("u1", "gold_designer")
        assert set(badge_system.list_badges("u1")) == {"fast_response", "gold_designer"}

    def test_revoke(self):
        badge_system = SkillBadge()
        badge_system.grant("u1", "fast_response")
        badge_system.revoke("u1", "fast_response")
        assert badge_system.list_badges("u1") == []

    def test_list_unknown_user(self):
        badge_system = SkillBadge()
        assert badge_system.list_badges("unknown") == []


class TestRiskWeight:
    def test_weight_of_known_dimension(self):
        rw = RiskWeight(weights={"punctuality": 2.0, "cleanliness": 1.0})
        assert rw.weight_of("punctuality") == 2.0
        assert rw.weight_of("cleanliness") == 1.0

    def test_weight_of_unknown_defaults_to_one(self):
        rw = RiskWeight()
        assert rw.weight_of("unknown") == 1.0
