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
    builders = server.task_factory._builders
    assert "buyer" in builders
    assert "tender" in builders


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
    """准入规则包含 business_license。"""
    server = _load_plugin()
    # rule_engine 应有至少 1 条 access_rule，且表达式包含 business_license
    assert len(server.rule_engine._access_rules) >= 1
    assert any(
        "business_license" in rule.expression
        for rule in server.rule_engine._access_rules
    )
