"""多插件并存端到端测试：同一 UMCPServer 同时加载三个插件，按 domain 各自走通完整流程。"""
from __future__ import annotations

import pytest

from umcp_core.core import DomainTag
from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.core.task import CustomTask
from umcp_core.server import UMCPServer


class _ConcreteUser(User):
    """User 是 ABC，测试中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def _make_user(
    user_id: str = "u1",
    credentials: list[str] | None = None,
    trust_score: float = 5.0,
) -> User:
    user = _ConcreteUser(user_id=user_id, name=user_id)
    user.metadata["credentials"] = credentials or []
    user.metadata["trust_score"] = trust_score
    return user


def _make_task(domain: str) -> CustomTask:
    return CustomTask(
        demander_id="u1",
        domain_tag=DomainTag.of(domain),
    )


@pytest.fixture
def server() -> UMCPServer:
    """加载三个插件的 server。"""
    s = UMCPServer()
    s.use_in_memory_repositories()
    s.load_plugin("ride_hailing")
    s.load_plugin("escort_driving")
    s.load_plugin("group_buying")
    s.start()
    return s


def test_load_three_plugins_simultaneously(server: UMCPServer):
    """同一 server 加载 3 个插件，无报错。"""
    assert len(server.plugins) == 3
    names = [p.name for p in server.plugins]
    assert "ride-hailing" in names
    assert "escort-driving" in names
    assert "group-buying" in names


def test_each_domain_uses_own_strategy(server: UMCPServer):
    """ride 用 InstantMatch，group_buying 用 ReverseAuction。"""
    from umcp_core.layers.l3 import InstantMatch, ReverseAuction

    ride_strategy = server.match_strategy_for("ride")
    gb_strategy = server.match_strategy_for("group_buying")
    escort_strategy = server.match_strategy_for("escort")

    assert isinstance(ride_strategy, InstantMatch)
    assert isinstance(gb_strategy, ReverseAuction)
    assert isinstance(escort_strategy, InstantMatch)
    # 三个策略应是不同实例
    assert ride_strategy is not gb_strategy
    assert ride_strategy is not escort_strategy


def test_each_domain_uses_own_payment(server: UMCPServer):
    """ride 走 DynamicPricing（20% 抽成），group_buying 走 InstallmentPayment（5% + 30% 订金）。"""
    from umcp_core.layers.l4 import DynamicPricing, InstallmentPayment

    ride_pay = server.payment_schema_for("ride")
    gb_pay = server.payment_schema_for("group_buying")

    assert isinstance(ride_pay, DynamicPricing)
    assert isinstance(gb_pay, InstallmentPayment)
    assert gb_pay.deposit_ratio == 0.3
    # ride_pay 的 commission_rule rate 应为 0.20
    assert ride_pay.commission_rule.rate == 0.20
    # gb_pay 的 commission_rule rate 应为 0.05
    assert gb_pay.commission_rule.rate == 0.05


def test_each_domain_uses_own_trust_dimensions(server: UMCPServer):
    """ride 与 group_buying 评价维度独立。"""
    ride_engine = server.trust_engine_for("ride")
    gb_engine = server.trust_engine_for("group_buying")

    # WeightedSumTrustEngine 内部维护 dimensions 配置
    assert ride_engine is not gb_engine
    # 通过实际记录评价验证维度独立
    from umcp_core.layers.l5 import Evaluation

    ride_eval = Evaluation(
        evaluator_id="buyer_1",
        evaluatee_id="driver_1",
        task_id="task_1",
        ratings={"punctuality": 5.0, "cleanliness": 4.0,
                 "driving_smoothness": 5.0, "communication": 4.0},
    )
    server.trust_engine_for("ride").record_evaluation(ride_eval)
    ride_profile = server.trust_engine_for("ride").evaluate("driver_1")
    assert ride_profile.get_score("punctuality") == 5.0

    # group_buying 的 driver_1 评价应为空（隔离）
    gb_profile = server.trust_engine_for("group_buying").evaluate("driver_1")
    assert gb_profile.get_score("punctuality") == 0.0


def test_access_rule_does_not_leak_across_domains(server: UMCPServer):
    """ride 的 driver_license 要求不卡 group_buying 买家。"""
    from umcp_core.layers.l5 import Evaluation

    # 用户只有 business_license，无 driver_license
    gb_user = _make_user(
        user_id="gb_buyer",
        credentials=["business_license"],
        trust_score=5.0,
    )

    # ride task：缺 driver_license，应拒绝
    ride_task = _make_task("ride")
    assert server.rule_engine.check_access(gb_user, ride_task) is False

    # group_buying task：有 business_license，应通过
    # 记录评价使 trustScore 通过 trust engine 路由达标（>= 3.0）
    server.trust_engine_for("group_buying").record_evaluation(
        Evaluation(
            evaluator_id="e1",
            evaluatee_id=gb_user.user_id,
            task_id="t1",
            ratings={
                "delivery": 5.0,
                "quality": 5.0,
                "service": 5.0,
                "cost_performance": 5.0,
            },
        )
    )
    gb_task = _make_task("group_buying")
    assert server.rule_engine.check_access(gb_user, gb_task) is True


def test_three_full_flows_in_one_server(server: UMCPServer):
    """同一 server 内串行执行三个完整交易流程，互不串扰。

    简化验证：每个 domain 各发起一次匹配，确认走对策略且无异常。
    完整支付/评价流程由单插件端到端测试覆盖，此处聚焦路由正确性。
    """
    from ride_hailing.resources import DriverResource
    from ride_hailing.tasks import RideTask

    # === ride 流程 ===
    driver = DriverResource(
        supplier_id="s_ride",
        domain_tag=DomainTag.of("ride"),
        current_lat=39.905,
        current_lng=116.408,
    )
    driver.register()
    server.resource_repo.save(driver)

    ride_task = RideTask(
        demander_id="d_ride",
        domain_tag=DomainTag.of("ride"),
        origin_lat=39.9042,
        origin_lng=116.4074,
        dest_lat=39.9590,
        dest_lng=116.4518,
    )
    ride_task.publish()

    candidates = server.resource_repo.find_available(DomainTag.of("ride"))
    result = server.match_strategy_for("ride").execute(ride_task, candidates)
    assert result.matched
    assert result.selected_resource_id == driver.resource_id

    # === escort 流程（最小验证：策略存在且可调用）===
    escort_strategy = server.match_strategy_for("escort")
    assert escort_strategy is not None

    # === group_buying 流程（最小验证：策略存在且类型正确）===
    from umcp_core.layers.l3 import ReverseAuction
    gb_strategy = server.match_strategy_for("group_buying")
    assert isinstance(gb_strategy, ReverseAuction)
