"""测试 L7 治理与规则层。"""

from __future__ import annotations

import pytest

from umcp_core.core import DomainTag, StandardTask, User
from umcp_core.layers.l7 import (
    Dispute,
    ExpressionAccessRule,
    NoopComplianceModule,
    RuleEngine,
    SimpleArbitrationPolicy,
)


class _Task(StandardTask):
    def task_type(self) -> str:
        return "test"


class _User(User):
    def authenticate(self, credential) -> bool:  # type: ignore[override]
        return True


class TestExpressionAccessRule:
    def test_has_credential_passes(self):
        rule = ExpressionAccessRule("hasCredential('driver_license')")
        user = _User(name="alice", metadata={"credentials": ["driver_license"]})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user, task)

    def test_missing_credential_fails(self):
        rule = ExpressionAccessRule("hasCredential('driver_license')")
        user = _User(name="alice", metadata={"credentials": []})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert not rule.check(user, task)

    def test_combined_expression_with_and(self):
        rule = ExpressionAccessRule(
            "hasCredential('driver_license') && trustScore >= 4.0"
        )
        user_ok = _User(
            name="alice",
            metadata={"credentials": ["driver_license"], "trust_score": 4.5},
        )
        user_low_score = _User(
            name="bob",
            metadata={"credentials": ["driver_license"], "trust_score": 3.5},
        )
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user_ok, task)
        assert not rule.check(user_low_score, task)

    def test_combined_expression_with_or(self):
        rule = ExpressionAccessRule(
            "hasCredential('vip') || trustScore >= 4.5"
        )
        user_vip = _User(
            name="alice",
            metadata={"credentials": ["vip"], "trust_score": 2.0},
        )
        user_high_score = _User(
            name="bob",
            metadata={"credentials": [], "trust_score": 4.8},
        )
        user_neither = _User(
            name="carol",
            metadata={"credentials": [], "trust_score": 3.0},
        )
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user_vip, task)
        assert rule.check(user_high_score, task)
        assert not rule.check(user_neither, task)


class TestRuleEngine:
    def test_check_access_all_rules_pass(self):
        engine = RuleEngine()
        engine.add_access_rule(ExpressionAccessRule("hasCredential('a')"))
        engine.add_access_rule(ExpressionAccessRule("hasCredential('b')"))
        user = _User(name="alice", metadata={"credentials": ["a", "b"]})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("test"))
        assert engine.check_access(user, task)

    def test_check_access_any_rule_fails(self):
        engine = RuleEngine()
        engine.add_access_rule(ExpressionAccessRule("hasCredential('a')"))
        engine.add_access_rule(ExpressionAccessRule("hasCredential('b')"))
        user = _User(name="alice", metadata={"credentials": ["a"]})  # 缺 b
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("test"))
        assert not engine.check_access(user, task)

    def test_arbitrate_default_policy(self):
        engine = RuleEngine()
        dispute = Dispute(
            dispute_id="dp1",
            deal_id="d1",
            initiator_id="d1",
            respondent_id="s1",
            reason="服务未完成",
        )
        result = engine.arbitrate(dispute)
        assert result.outcome == "cancelled"

    def test_audit_default_passes(self):
        from umcp_core.core import Deal

        engine = RuleEngine()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        assert engine.audit(deal)


class TestComplianceModule:
    def test_noop_returns_true(self):
        from umcp_core.core import Deal

        module = NoopComplianceModule()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        assert module.audit(deal)

    def test_noop_required_compliances_empty(self):
        module = NoopComplianceModule()
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("test"))
        assert module.get_required_compliances(task) == []
