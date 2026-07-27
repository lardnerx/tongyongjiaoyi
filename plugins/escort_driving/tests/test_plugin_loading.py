"""测试陪驾插件加载机制。"""

from __future__ import annotations

import pytest

from umcp_core.server import UMCPServer


class TestEscortPluginLoading:
    @pytest.fixture
    def server_with_plugin(self) -> UMCPServer:
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.load_plugin("escort_driving")
        server.start()
        return server

    def test_plugin_appears_in_loaded_list(self, server_with_plugin: UMCPServer):
        plugins = server_with_plugin.plugins
        assert len(plugins) == 1
        assert plugins[0].name == "escort-driving"
        assert plugins[0].version == "1.0.0"

    def test_task_factory_registered_escort_type(self, server_with_plugin: UMCPServer):
        assert "escort" in server_with_plugin.task_factory._builders

    def test_match_strategy_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l3 import InstantMatch

        assert isinstance(server_with_plugin.match_strategy, InstantMatch)

    def test_payment_schema_injected_as_hourly(self, server_with_plugin: UMCPServer):
        """支付模式应为 Hourly（按时长计费）。"""
        from umcp_core.layers.l4 import Hourly

        assert isinstance(server_with_plugin.payment_schema, Hourly)

    def test_trust_engine_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l5 import WeightedSumTrustEngine

        assert isinstance(server_with_plugin.trust_engine, WeightedSumTrustEngine)

    def test_access_rule_injected(self, server_with_plugin: UMCPServer):
        """准入规则应包含 coach_license 要求。"""
        from umcp_core.core import DomainTag, StandardTask, User
        from umcp_core.layers.l5 import Evaluation

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        class _User(User):
            def authenticate(self, credential) -> bool:
                return True

        # 无资质的用户
        user_no_cred = _User(name="alice", metadata={"credentials": [], "trust_score": 5.0})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("escort"))
        assert not server_with_plugin.rule_engine.check_access(user_no_cred, task)

        # 有资质且信用达标的用户
        user_ok = _User(
            name="bob",
            metadata={"credentials": ["coach_license"], "trust_score": 4.5},
        )
        # 记录评价使 trustScore 通过 trust engine 路由达标（>= 4.0）
        server_with_plugin.trust_engine.record_evaluation(
            Evaluation(
                evaluator_id="e1",
                evaluatee_id=user_ok.user_id,
                task_id="t1",
                ratings={
                    "teaching_ability": 5.0,
                    "patience": 5.0,
                    "safety_record": 5.0,
                },
            )
        )
        assert server_with_plugin.rule_engine.check_access(user_ok, task)

    def test_trust_dimensions_configured(self, server_with_plugin: UMCPServer):
        """信任引擎应配置 3 个维度。"""
        profile = server_with_plugin.trust_engine.evaluate("u_test")
        assert "teaching_ability" in profile.dimension_scores
        assert "patience" in profile.dimension_scores
        assert "safety_record" in profile.dimension_scores

    def test_hourly_rate_configured(self, server_with_plugin: UMCPServer):
        """时薪应为 80 元/小时。"""
        from umcp_core.core import Deal, DomainTag, StandardTask

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "escort"

        task = _Task(demander_id="d1", domain_tag=DomainTag.of("escort"))
        task.custom_fields["actual_hours"] = 2.0
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
            final_amount=0.0,  # Hourly 不使用 deal.final_amount
        )
        order = server_with_plugin.payment_schema.calculate(task, deal)
        # 2 小时 × 80 元/小时 = 160 元
        assert order.total_amount == 160.0
        # 20% 抽成 = 32 元
        assert order.commission == 32.0
