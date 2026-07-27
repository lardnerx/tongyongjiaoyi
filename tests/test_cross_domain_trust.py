"""跨域身份与信用单元测试。"""
from __future__ import annotations

from umcp_core.layers.l5 import (
    MeanTrustAggregator,
    TrustAggregator,
    TrustEngine,
    WeightedSumTrustEngine,
)
from umcp_core.layers.l5.trust import Evaluation


def test_mean_trust_aggregator_empty_engines():
    """无 engine 时返回 0.0。"""
    aggregator = MeanTrustAggregator()
    assert aggregator.aggregate("u1", {}) == 0.0


def test_mean_trust_aggregator_arithmetic_mean():
    """3 个 engine 的 overall_score 算术平均。"""
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_escort = WeightedSumTrustEngine(dimensions=["overall"])
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])

    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    engine_escort.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 4.0})
    )
    engine_gb.record_evaluation(
        Evaluation(evaluator_id="e3", evaluatee_id="u1", task_id="t3", ratings={"overall": 3.0})
    )

    engines = {"ride": engine_ride, "escort": engine_escort, "group_buying": engine_gb}
    aggregator = MeanTrustAggregator()
    assert aggregator.aggregate("u1", engines) == 4.0


def test_mean_trust_aggregator_user_not_in_engine():
    """用户在某 engine 没有评价记录时，overall_score 为 0.0，纳入平均。"""
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])

    engines = {"ride": engine_ride, "group_buying": engine_gb}
    aggregator = MeanTrustAggregator()
    assert aggregator.aggregate("u1", engines) == 2.5


def test_trust_aggregator_is_abstract():
    """TrustAggregator 是抽象基类，不能直接实例化。"""
    import pytest
    with pytest.raises(TypeError):
        TrustAggregator()  # type: ignore[abstract]
