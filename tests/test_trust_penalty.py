"""验证 TrustEngine.apply_penalty 扣分逻辑。"""
from __future__ import annotations

from umcp_core.layers.l5.trust import Evaluation, WeightedSumTrustEngine


def test_apply_penalty_reduces_overall_score():
    """扣分应降低 overall_score，不低于 0。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    # 先记录一个正向评分，使 overall_score > 0
    engine.record_evaluation(Evaluation(
        evaluator_id="coach1",
        evaluatee_id="student1",
        task_id="t1",
        ratings={"overall": 4.0},
        comment="",
    ))
    profile = engine.evaluate("student1")
    assert profile.overall_score == 4.0

    # 扣 1.5 分
    engine.apply_penalty("student1", 1.5, reason="预约单临时取消")
    profile = engine.evaluate("student1")
    assert profile.overall_score == 2.5

    # 再扣 5 分，应降到 0（不低于 0）
    engine.apply_penalty("student1", 5.0, reason="再次取消")
    profile = engine.evaluate("student1")
    assert profile.overall_score == 0.0


def test_apply_penalty_unknown_user_starts_from_zero():
    """未评价过的用户从 0 分起扣，仍为 0。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    engine.apply_penalty("unknown_user", 2.0, reason="测试")
    profile = engine.evaluate("unknown_user")
    assert profile.overall_score == 0.0


def test_apply_penalty_negative_points_ignored():
    """负分应被忽略（不允许通过 apply_penalty 加分）。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    engine.apply_penalty("u1", -1.0, reason="非法")
    profile = engine.evaluate("u1")
    assert profile.overall_score == 0.0


def test_apply_penalty_does_not_affect_dimension_scores():
    """扣分不影响维度分（维度分反映历史评价）。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    engine.record_evaluation(Evaluation(
        evaluator_id="coach1",
        evaluatee_id="student1",
        task_id="t1",
        ratings={"overall": 4.0},
        comment="",
    ))
    engine.apply_penalty("student1", 1.5, reason="取消")
    profile = engine.evaluate("student1")
    # 维度分不变
    assert profile.dimension_scores["overall"] == 4.0
    # overall_score 扣分后 = 4.0 - 1.5 = 2.5
    assert profile.overall_score == 2.5


def test_apply_penalty_accumulates():
    """多次扣分应累计。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    engine.record_evaluation(Evaluation(
        evaluator_id="coach1",
        evaluatee_id="student1",
        task_id="t1",
        ratings={"overall": 5.0},
        comment="",
    ))
    engine.apply_penalty("student1", 1.0, reason="第一次取消")
    engine.apply_penalty("student1", 2.0, reason="第二次取消")
    profile = engine.evaluate("student1")
    # 5.0 - 1.0 - 2.0 = 2.0
    assert profile.overall_score == 2.0
