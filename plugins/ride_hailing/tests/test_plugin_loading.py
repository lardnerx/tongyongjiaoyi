"""测试插件加载机制。"""

from __future__ import annotations

import pytest

from umcp_core.server import UMCPServer


class TestPluginLoading:
    @pytest.fixture
    def server_with_plugin(self) -> UMCPServer:
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.load_plugin("ride_hailing")
        server.start()
        return server

    def test_plugin_appears_in_loaded_list(self, server_with_plugin: UMCPServer):
        plugins = server_with_plugin.plugins
        assert len(plugins) == 1
        assert plugins[0].name == "ride-hailing"
        assert plugins[0].version == "1.0.0"

    def test_task_factory_registered_ride_type(self, server_with_plugin: UMCPServer):
        assert "ride" in server_with_plugin.task_factory._builders

    def test_match_strategy_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l3 import InstantMatch

        assert isinstance(server_with_plugin.match_strategy, InstantMatch)

    def test_payment_schema_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l4 import DynamicPricing

        assert isinstance(server_with_plugin.payment_schema, DynamicPricing)

    def test_trust_engine_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l5 import WeightedSumTrustEngine

        assert isinstance(server_with_plugin.trust_engine, WeightedSumTrustEngine)

    def test_access_rule_injected(self, server_with_plugin: UMCPServer):
        """准入规则应包含 driver_license 要求。"""
        # 准入规则在 _apply_manifest 中通过 ExpressionAccessRule 添加
        # 验证：无 driver_license 的用户应被拒绝
        from umcp_core.core import DomainTag, StandardTask, User

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "ride"

        class _User(User):
            def authenticate(self, credential) -> bool:
                return True

        # 无资质的用户
        user_no_cred = _User(name="alice", metadata={"credentials": [], "trust_score": 5.0})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert not server_with_plugin.rule_engine.check_access(user_no_cred, task)

        # 有资质且信用达标的用户
        user_ok = _User(
            name="bob",
            metadata={"credentials": ["driver_license"], "trust_score": 4.5},
        )
        assert server_with_plugin.rule_engine.check_access(user_ok, task)

    def test_trust_dimensions_configured(self, server_with_plugin: UMCPServer):
        """信任引擎应配置 4 个维度。"""
        profile = server_with_plugin.trust_engine.evaluate("u_test")
        assert "punctuality" in profile.dimension_scores
        assert "cleanliness" in profile.dimension_scores
        assert "driving_smoothness" in profile.dimension_scores
        assert "communication" in profile.dimension_scores

    def test_commission_rate_configured(self, server_with_plugin: UMCPServer):
        """抽成比例应为 20%。"""
        from umcp_core.core import Deal, DomainTag, StandardTask

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "ride"

        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.custom_fields["base_price"] = 100.0
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
            final_amount=100.0,
        )
        order = server_with_plugin.payment_schema.calculate(task, deal)
        assert order.commission == 20.0  # 20% of 100
