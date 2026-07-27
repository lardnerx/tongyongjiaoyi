"""多插件路由单元测试。"""
from __future__ import annotations

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l7 import ExpressionAccessRule, RuleEngine


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
