"""多插件路由单元测试。"""
from __future__ import annotations

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l3 import InstantMatch, ReverseAuction
from umcp_core.layers.l4 import DynamicPricing, InstallmentPayment, FlatCommissionRule
from umcp_core.layers.l5 import WeightedSumTrustEngine
from umcp_core.layers.l7 import ExpressionAccessRule, RuleEngine
from umcp_core.server import UMCPServer


class _ConcreteUser(User):
    """User 是 ABC，测试中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def _make_user(credentials: list[str] | None = None, trust_score: float = 5.0) -> User:
    user = _ConcreteUser(user_id="u1", name="alice")
    user.metadata["credentials"] = credentials or []
    user.metadata["trust_score"] = trust_score
    return user


def _make_task(domain: str) -> CustomTask:
    return CustomTask(
        demander_id="u1",
        domain_tag=DomainTag.of(domain),
    )


def test_rule_engine_domain_scoped_access():
    """domain 范围的 access_rule 只对该 domain 生效。"""
    engine = RuleEngine()
    # ride domain 要求 driver_license
    engine.add_access_rule(
        ExpressionAccessRule("hasCredential('driver_license')"),
        domain="ride",
    )
    # group_buying domain 要求 business_license
    engine.add_access_rule(
        ExpressionAccessRule("hasCredential('business_license')"),
        domain="group_buying",
    )

    # ride task：用户有 driver_license 但无 business_license，应通过
    ride_user = _make_user(credentials=["driver_license"])
    ride_task = _make_task("ride")
    assert engine.check_access(ride_user, ride_task) is True

    # group_buying task：同一用户无 business_license，应拒绝
    gb_task = _make_task("group_buying")
    assert engine.check_access(ride_user, gb_task) is False


def test_rule_engine_global_fallback():
    """无 domain 参数的 access_rule 对所有 domain 生效。"""
    engine = RuleEngine()
    # 全局规则：trustScore >= 3.0
    engine.add_access_rule(ExpressionAccessRule("trustScore >= 3.0"))

    # 低信任用户在任何 domain 都应被拒绝
    low_trust_user = _make_user(trust_score=2.0)
    assert engine.check_access(low_trust_user, _make_task("ride")) is False
    assert engine.check_access(low_trust_user, _make_task("group_buying")) is False

    # 高信任用户在任何 domain 都应通过
    high_trust_user = _make_user(trust_score=5.0)
    assert engine.check_access(high_trust_user, _make_task("ride")) is True
    assert engine.check_access(high_trust_user, _make_task("group_buying")) is True


def test_register_match_strategy_by_domain():
    """register_match_strategy 按 domain 注册，*_for 按 domain 查询。"""
    server = UMCPServer()
    ride_strategy = InstantMatch()
    gb_strategy = ReverseAuction()

    server.register_match_strategy("ride", ride_strategy)
    server.register_match_strategy("group_buying", gb_strategy)

    assert server.match_strategy_for("ride") is ride_strategy
    assert server.match_strategy_for("group_buying") is gb_strategy
    # DomainTag 也能作为参数
    assert server.match_strategy_for(DomainTag.of("ride")) is ride_strategy


def test_match_strategy_for_falls_back_to_default():
    """未注册的 domain 回退到单值属性。"""
    server = UMCPServer()
    default_strategy = InstantMatch()
    server.set_match_strategy(default_strategy)

    # 未注册 domain 应回退到默认
    assert server.match_strategy_for("unknown_domain") is default_strategy
    # 单值属性本身也保留
    assert server.match_strategy is default_strategy


def test_payment_schema_routing():
    """payment_schema 按 domain 路由。"""
    server = UMCPServer()
    ride_pay = DynamicPricing(surge_factor=1.0, commission_rule=FlatCommissionRule(rate=0.20))
    gb_pay = InstallmentPayment(deposit_ratio=0.3, commission_rule=FlatCommissionRule(rate=0.05))

    server.register_payment_schema("ride", ride_pay)
    server.register_payment_schema("group_buying", gb_pay)

    assert server.payment_schema_for("ride") is ride_pay
    assert server.payment_schema_for("group_buying") is gb_pay


def test_trust_engine_routing():
    """trust_engine 按 domain 路由。"""
    server = UMCPServer()
    ride_engine = WeightedSumTrustEngine(dimensions=["punctuality", "cleanliness"])
    gb_engine = WeightedSumTrustEngine(dimensions=["delivery", "quality"])

    server.register_trust_engine("ride", ride_engine)
    server.register_trust_engine("group_buying", gb_engine)

    assert server.trust_engine_for("ride") is ride_engine
    assert server.trust_engine_for("group_buying") is gb_engine


def test_register_updates_single_value_property():
    """register_* 同时更新单值属性作为兜底（指向最后注册的）。"""
    server = UMCPServer()
    s1 = InstantMatch()
    s2 = ReverseAuction()

    server.register_match_strategy("ride", s1)
    assert server.match_strategy is s1  # 单值指向最后注册的

    server.register_match_strategy("group_buying", s2)
    assert server.match_strategy is s2  # 单值更新为最后注册的


def test_apply_manifest_registers_by_domain():
    """_apply_manifest 读取 domain 字段并按 domain 注册。"""
    server = UMCPServer()
    manifest = {
        "name": "test-plugin",
        "version": "1.0.0",
        "domain": "test_domain",
        "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
        "payment_schema": "umcp_core.layers.l4.DynamicPricing",
        "trust_engine": "umcp_core.layers.l5.WeightedSumTrustEngine",
        "access_rule_expression": "trustScore >= 3.0",
    }
    from umcp_core.server import PluginDescriptor
    from pathlib import Path
    descriptor = PluginDescriptor(manifest, Path("."))
    server._apply_manifest(descriptor)

    # 按 domain 应能查到对应策略
    assert server.match_strategy_for("test_domain") is not None
    assert isinstance(server.match_strategy_for("test_domain"), InstantMatch)
    # access_rule 也应注册到 test_domain
    gb_task = _make_task("test_domain")
    high_trust_user = _make_user(trust_score=5.0)
    # _apply_manifest 后 trust_engine 已通过 register_trust_engine 同步到
    # rule_engine，trustScore 走 engine.evaluate() 路径（新用户返回 0.0）。
    # 通过 record_evaluation 预填充 profile 使分数达标。
    from umcp_core.layers.l5 import Evaluation

    server.trust_engine_for("test_domain").record_evaluation(
        Evaluation(
            evaluator_id="e1",
            evaluatee_id=high_trust_user.user_id,
            task_id="t1",
            ratings={"overall": 5.0},  # WeightedSumTrustEngine 默认维度
        )
    )
    assert server.rule_engine.check_access(high_trust_user, gb_task) is True


def test_apply_manifest_without_domain_falls_back_to_single_value():
    """缺 domain 字段时只更新单值属性，不注册到 domain 表（向后兼容）。"""
    server = UMCPServer()
    manifest = {
        "name": "legacy-plugin",
        "version": "1.0.0",
        "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    }
    from umcp_core.server import PluginDescriptor
    from pathlib import Path
    descriptor = PluginDescriptor(manifest, Path("."))
    server._apply_manifest(descriptor)

    # 单值属性应被设置
    assert isinstance(server.match_strategy, InstantMatch)
    # 但 domain 表应为空，*_for 查不到
    assert server.match_strategy_for("any_domain") is server.match_strategy  # 回退到默认


def test_register_normalizes_domain_to_lowercase():
    """register_* 将 domain 小写化，与 DomainTag.of() 行为一致。"""
    server = UMCPServer()
    ride_strategy = InstantMatch()

    # 用大写 domain 注册
    server.register_match_strategy("Ride", ride_strategy)

    # 用小写查询应能命中
    assert server.match_strategy_for("ride") is ride_strategy
    # 用 DomainTag 查询也应命中（DomainTag.of 已小写化）
    assert server.match_strategy_for(DomainTag.of("RIDE")) is ride_strategy


def test_apply_manifest_with_domain_list():
    """_apply_manifest 支持 domain 为列表（跨域插件）。"""
    server = UMCPServer()
    manifest = {
        "name": "cross-domain-plugin",
        "version": "1.0.0",
        "domain": ["ride", "escort"],
        "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    }
    from umcp_core.server import PluginDescriptor
    from pathlib import Path
    descriptor = PluginDescriptor(manifest, Path("."))
    server._apply_manifest(descriptor)

    # 两个 domain 都应能查到策略
    assert isinstance(server.match_strategy_for("ride"), InstantMatch)
    assert isinstance(server.match_strategy_for("escort"), InstantMatch)
    # 且应是同一实例
    assert server.match_strategy_for("ride") is server.match_strategy_for("escort")


def test_payment_schema_for_with_domaintag_and_fallback():
    """payment_schema_for 支持 DomainTag 入参和未命中回退。"""
    server = UMCPServer()
    ride_pay = DynamicPricing(surge_factor=1.0, commission_rule=FlatCommissionRule(rate=0.20))
    server.register_payment_schema("ride", ride_pay)

    # DomainTag 入参
    assert server.payment_schema_for(DomainTag.of("ride")) is ride_pay
    # 未命中回退到单值属性（register 后单值被设为 ride_pay）
    assert server.payment_schema_for("unknown") is ride_pay


def test_trust_engine_for_with_domaintag_and_fallback():
    """trust_engine_for 支持 DomainTag 入参和未命中回退。"""
    server = UMCPServer()
    ride_engine = WeightedSumTrustEngine(dimensions=["punctuality"])
    server.register_trust_engine("ride", ride_engine)

    # DomainTag 入参
    assert server.trust_engine_for(DomainTag.of("ride")) is ride_engine
    # 未命中回退到单值属性
    assert server.trust_engine_for("unknown") is ride_engine
