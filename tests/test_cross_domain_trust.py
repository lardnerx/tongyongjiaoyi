"""跨域身份与信用单元测试。"""
from __future__ import annotations

import pytest

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l5 import (
    MeanTrustAggregator,
    TrustAggregator,
    TrustEngine,
    WeightedSumTrustEngine,
)
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.layers.l7 import ExpressionAccessRule, RuleContext, RuleEngine


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
    with pytest.raises(TypeError):
        TrustAggregator()  # type: ignore[abstract]


# ============================================================================
# RuleContext 按 task.domain 路由 trust_score
# ============================================================================


class _ConcreteUser(User):
    """User 是 ABC，测试中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def _make_user(credentials=None, trust_score=5.0):
    user = _ConcreteUser(user_id="u1", name="alice")
    user.metadata["credentials"] = credentials or []
    user.metadata["trust_score"] = trust_score
    return user


def _make_task(domain):
    return CustomTask(demander_id="u1", domain_tag=DomainTag.of(domain))


def test_rule_context_trust_score_routes_by_domain():
    """RuleContext.trust_score 按 task.domain_tag 路由到对应 engine 的 overall_score。"""
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])
    engine_gb.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.0})
    )

    # user.metadata['trust_score'] 设为 1.0（不应该被读到）
    user = _make_user(trust_score=1.0)
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # 注入 domain→engine 路由
    ctx_ride = RuleContext(
        user=user,
        task=ride_task,
        trust_engine_for_domain=lambda d: {"ride": engine_ride, "group_buying": engine_gb}.get(d),
    )
    ctx_gb = RuleContext(
        user=user,
        task=gb_task,
        trust_engine_for_domain=lambda d: {"ride": engine_ride, "group_buying": engine_gb}.get(d),
    )

    # 应该读到对应 domain 的 engine 分数，而非 metadata
    assert ctx_ride.trust_score == 5.0
    assert ctx_gb.trust_score == 3.0


def test_rule_context_falls_back_to_metadata():
    """未绑定 lookup 时回退到 user.metadata['trust_score']（向后兼容）。"""
    user = _make_user(trust_score=4.2)
    task = _make_task("ride")
    ctx = RuleContext(user=user, task=task)  # 不传 trust_engine_for_domain
    assert ctx.trust_score == 4.2


def test_rule_context_falls_back_when_domain_not_registered():
    """lookup 已注入但 task.domain 没有对应 engine 时，回退到 metadata。"""
    user = _make_user(trust_score=4.5)
    task = _make_task("unknown_domain")
    # 只注册了 ride，task 是 unknown_domain
    ctx = RuleContext(
        user=user,
        task=task,
        trust_engine_for_domain=lambda d: {"ride": WeightedSumTrustEngine()}.get(d),
    )
    assert ctx.trust_score == 4.5


def test_expression_access_rule_check_routes_trust_score():
    """ExpressionAccessRule.check 在绑定 lookup 后按 task.domain 路由 trust_score。"""
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])
    engine_gb.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 2.0})
    )

    rule = ExpressionAccessRule("trustScore >= 4.0")
    rule.bind_trust_engine_lookup(
        lambda d: {"ride": engine_ride, "group_buying": engine_gb}.get(d)
    )

    user = _make_user(trust_score=1.0)  # metadata 设为 1.0，验证不被读到
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # ride 域 5.0 >= 4.0 通过
    assert rule.check(user, ride_task) is True
    # gb 域 2.0 < 4.0 拒绝
    assert rule.check(user, gb_task) is False


def test_bind_trust_engine_lookup_is_idempotent():
    """bind_trust_engine_lookup 幂等：重复调用不会覆盖已绑定的 lookup。"""
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])
    engine_gb.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 2.0})
    )

    rule = ExpressionAccessRule("trustScore >= 4.0")
    first_lookup = lambda d: {"ride": engine_ride}.get(d)
    second_lookup = lambda d: {"group_buying": engine_gb}.get(d)

    rule.bind_trust_engine_lookup(first_lookup)
    # 再次绑定不应覆盖
    rule.bind_trust_engine_lookup(second_lookup)

    user = _make_user(trust_score=1.0)
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # 应该用 first_lookup（ride 域有 5.0），ride task 通过
    assert rule.check(user, ride_task) is True
    # gb task 用 first_lookup 查不到 engine，回退到 metadata=1.0 < 4.0，拒绝
    assert rule.check(user, gb_task) is False


# ============================================================================
# RuleEngine 持有 domain→TrustEngine 映射并在 check_access 注入路由
# ============================================================================


def test_rule_engine_registers_trust_engine():
    """RuleEngine.register_trust_engine 把 engine 加入 _domain_trust_engines。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])

    engine.register_trust_engine("ride", ride_te)

    assert engine._domain_trust_engines["ride"] is ride_te


def test_rule_engine_register_trust_engine_lowercases_domain():
    """register_trust_engine 将 domain 统一小写化存储。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])

    engine.register_trust_engine("RIDE", ride_te)

    # DomainTag.of('ride').value == 'ride'，查询时用小写
    assert "ride" in engine._domain_trust_engines
    assert "RIDE" not in engine._domain_trust_engines


def test_expression_access_rule_uses_domain_score():
    """ExpressionAccessRule 的 trustScore 按 task.domain 取值（通过 RuleEngine 注入）。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 2.0})
    )

    engine.register_trust_engine("ride", ride_te)
    engine.register_trust_engine("group_buying", gb_te)

    # 注册按 domain 隔离的 access_rule：trustScore >= 3.0
    engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="ride",
    )
    engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="group_buying",
    )

    user = _make_user(trust_score=1.0)  # metadata 设为 1.0，验证不被读到
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # ride 域 5.0 >= 3.0 通过
    assert engine.check_access(user, ride_task) is True
    # gb 域 2.0 < 3.0 拒绝
    assert engine.check_access(user, gb_task) is False


def test_check_access_injects_lookup_only_once():
    """check_access 注入 lookup 是幂等的（多次调用不覆盖）。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    engine.register_trust_engine("ride", ride_te)

    rule = ExpressionAccessRule("trustScore >= 0.0")
    engine.add_access_rule(rule, domain="ride")

    user = _make_user(trust_score=1.0)
    task = _make_task("ride")

    engine.check_access(user, task)
    first_lookup = rule._trust_engine_lookup
    assert first_lookup is not None

    # 再次调用不应覆盖
    engine.check_access(user, task)
    assert rule._trust_engine_lookup is first_lookup
