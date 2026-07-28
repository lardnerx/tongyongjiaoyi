"""集采插件加载机制测试。"""
from __future__ import annotations

from umcp_core.layers.l3 import ReverseAuction
from umcp_core.layers.l4 import InstallmentPayment
from umcp_core.layers.l5 import WeightedSumTrustEngine
from umcp_core.server import UMCPServer


def _load_plugin() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("group_buying")
    return server


def test_plugin_loads_successfully():
    """插件能成功加载。"""
    server = _load_plugin()
    assert len(server.plugins) == 1
    assert server.plugins[0].name == "group-buying"
    assert server.plugins[0].version == "1.0.0"


def test_task_factory_registers_buyer_and_tender_types():
    """task_factory 注册了 buyer 和 tender 两种任务类型。"""
    server = _load_plugin()
    assert server.task_factory.is_registered("buyer")
    assert server.task_factory.is_registered("tender")


def test_match_strategy_is_reverse_auction():
    """match_strategy 为 ReverseAuction。"""
    server = _load_plugin()
    assert isinstance(server.match_strategy, ReverseAuction)


def test_match_strategy_has_scorer():
    """match_strategy 注入了 scorer。"""
    server = _load_plugin()
    assert server.match_strategy.scorer is not None


def test_match_strategy_has_credential_filter():
    """match_strategy 注入了 CredentialFilter。"""
    server = _load_plugin()
    from umcp_core.layers.l3 import CredentialFilter
    assert any(isinstance(f, CredentialFilter) for f in server.match_strategy.filters)


def test_payment_schema_is_installment_payment():
    """payment_schema 为 InstallmentPayment。"""
    server = _load_plugin()
    assert isinstance(server.payment_schema, InstallmentPayment)


def test_payment_schema_deposit_ratio_configured():
    """deposit_ratio 配置为 0.3。"""
    server = _load_plugin()
    assert server.payment_schema.deposit_ratio == 0.3


def test_trust_engine_is_weighted_sum_with_4_dimensions():
    """trust_engine 为 WeightedSumTrustEngine，4 维评价。"""
    server = _load_plugin()
    assert isinstance(server.trust_engine, WeightedSumTrustEngine)
    assert len(server.trust_engine.dimensions) == 4
    assert "delivery" in server.trust_engine.dimensions
    assert "quality" in server.trust_engine.dimensions
    assert "service" in server.trust_engine.dimensions
    assert "cost_performance" in server.trust_engine.dimensions


def test_access_rule_includes_business_license():
    """准入规则要求 business_license 且 trustScore >= 3.0。

    通过 check_access 行为验证（避免直接访问私有属性 _access_rules，
    因为 access_rule 现在按 domain 注册到 _domain_access_rules）。
    """
    from umcp_core.core import DomainTag, User
    from umcp_core.core.task import CustomTask
    from umcp_core.layers.l5 import Evaluation

    server = _load_plugin()

    class _User(User):
        def authenticate(self, credential) -> bool:
            return True

    task = CustomTask(demander_id="d1", domain_tag=DomainTag.of("group_buying"))

    # 无 business_license：即使信用达标也应被拒绝
    user_no_license = _User(
        name="alice",
        metadata={"credentials": [], "trust_score": 5.0},
    )
    assert not server.rule_engine.check_access(user_no_license, task)

    # 有 business_license 但信用不达标：应被拒绝
    user_low_trust = _User(
        name="bob",
        metadata={"credentials": ["business_license"], "trust_score": 2.0},
    )
    assert not server.rule_engine.check_access(user_low_trust, task)

    # 有 business_license 且信用达标：应通过
    user_ok = _User(
        name="carol",
        metadata={"credentials": ["business_license"], "trust_score": 5.0},
    )
    # 记录评价使 trustScore 通过 trust engine 路由达标（>= 3.0）
    server.trust_engine.record_evaluation(
        Evaluation(
            evaluator_id="e1",
            evaluatee_id=user_ok.user_id,
            task_id="t1",
            ratings={
                "delivery": 5.0,
                "quality": 5.0,
                "service": 5.0,
                "cost_performance": 5.0,
            },
        )
    )
    assert server.rule_engine.check_access(user_ok, task)
