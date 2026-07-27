"""端到端测试：跨域 trust_score 隔离与聚合。"""
from __future__ import annotations

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l5 import TrustAggregator, WeightedSumTrustEngine
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.layers.l7 import ExpressionAccessRule
from umcp_core.server import UMCPServer


class _E2EUser(User):
    """User 是 ABC，测试中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def _make_user(user_id="u1", credentials=None, trust_score=5.0):
    user = _E2EUser(user_id=user_id, name="alice")
    user.metadata["credentials"] = credentials or []
    user.metadata["trust_score"] = trust_score
    return user


def _make_task(domain, demander_id="u1"):
    return CustomTask(demander_id=demander_id, domain_tag=DomainTag.of(domain))


def _setup_server_with_two_domains():
    """加载 ride + group_buying 两个 domain 的 TrustEngine。"""
    server = UMCPServer()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    server.register_trust_engine("ride", ride_te)
    server.register_trust_engine("group_buying", gb_te)
    # 按 domain 注册 access_rule：trustScore >= 3.0
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="ride",
    )
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="group_buying",
    )
    return server, ride_te, gb_te


def test_trust_score_isolated_across_domains():
    """同一用户在 ride 域打分 5.0，在 group_buying 域仍为 0.0（隔离）。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )

    # ride 域 u1 = 5.0
    assert ride_te.evaluate("u1").overall_score == 5.0
    # group_buying 域 u1 仍为 0.0（评价数据隔离）
    assert gb_te.evaluate("u1").overall_score == 0.0


def test_access_rule_uses_domain_trust_score():
    """ride task 用 ride 域 score 判断准入；gb task 用 gb 域 score 判断（不串扰）。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    # ride 域打 5.0，gb 域打 2.0
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 2.0})
    )

    # user.metadata['trust_score'] = 1.0（验证不被读到）
    user = _make_user(trust_score=1.0)
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # ride 域 5.0 >= 3.0 通过
    assert server.rule_engine.check_access(user, ride_task) is True
    # gb 域 2.0 < 3.0 拒绝
    assert server.rule_engine.check_access(user, gb_task) is False


def test_aggregate_trust_score_across_domains():
    """ride 域 4.8 + gb 域 3.5 → 聚合 ≈ 4.15。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    # ride 域打 4.8（通过 record_evaluation 的移动平均，需要从 0 起步打 4.8 → 4.8）
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 4.8})
    )
    # gb 域打 3.5
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.5})
    )

    # 算术平均 (4.8 + 3.5) / 2 = 4.15
    aggregated = server.aggregate_trust_score("u1")
    assert abs(aggregated - 4.15) < 0.001


def test_low_trust_in_one_domain_blocks_only_that_domain():
    """ride 域低分（2.0）只卡 ride task，不卡 gb task。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    # ride 域打 2.0（低分），gb 域打 5.0（高分）
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 2.0})
    )
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 5.0})
    )

    user = _make_user(trust_score=1.0)  # metadata 不应被读到
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # ride 域 2.0 < 3.0 拒绝
    assert server.rule_engine.check_access(user, ride_task) is False
    # gb 域 5.0 >= 3.0 通过（不被 ride 域低分影响）
    assert server.rule_engine.check_access(user, gb_task) is True


def test_custom_aggregator_via_server():
    """注入自定义聚合策略（取最低分），验证 server.aggregate_trust_score 使用它。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.0})
    )

    class MinTrustAggregator(TrustAggregator):
        def aggregate(self, user_id, engines):
            if not engines:
                return 0.0
            return min(e.evaluate(user_id).overall_score for e in engines.values())

    server.set_trust_aggregator(MinTrustAggregator())
    # 取最低分 min(5.0, 3.0) = 3.0
    assert server.aggregate_trust_score("u1") == 3.0
