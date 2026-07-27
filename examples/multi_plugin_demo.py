"""多插件并存 Demo：在同一 UMCPServer 上跑通三 domain 完整流程。

验证目标：
1. 三个插件可同时加载到同一 server
2. 按 domain 路由到各自的 match_strategy / payment_schema / trust_engine
3. access_rule 按 domain 隔离，互不串扰

直接运行：python examples/multi_plugin_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 将 src 和 plugins 加入 sys.path，使脚本可独立运行
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "plugins"))

from umcp_core.core import DomainTag
from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.core.task import CustomTask
from umcp_core.server import UMCPServer


class _DemoUser(User):
    """User 是 ABC，demo 中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def main() -> None:
    print("=" * 60)
    print("UMCP 多插件并存 Demo")
    print("=" * 60)

    # ===== 1. 加载三个插件 =====
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("ride_hailing")
    server.load_plugin("escort_driving")
    server.load_plugin("group_buying")
    server.start()

    print(f"\n[1] 已加载插件: {[p.name for p in server.plugins]}")

    # ===== 2. 验证策略路由 =====
    from umcp_core.layers.l3 import InstantMatch, ReverseAuction
    from umcp_core.layers.l4 import DynamicPricing, InstallmentPayment

    ride_match = server.match_strategy_for("ride")
    escort_match = server.match_strategy_for("escort")
    gb_match = server.match_strategy_for("group_buying")

    print(f"\n[2] 匹配策略路由:")
    print(f"    ride         -> {type(ride_match).__name__}")
    print(f"    escort       -> {type(escort_match).__name__}")
    print(f"    group_buying -> {type(gb_match).__name__}")
    assert isinstance(ride_match, InstantMatch)
    assert isinstance(escort_match, InstantMatch)
    assert isinstance(gb_match, ReverseAuction)

    ride_pay = server.payment_schema_for("ride")
    gb_pay = server.payment_schema_for("group_buying")
    print(f"\n[3] 支付模式路由:")
    print(
        f"    ride         -> {type(ride_pay).__name__} "
        f"(commission_rate={ride_pay.commission_rule.rate})"
    )
    print(
        f"    group_buying -> {type(gb_pay).__name__} "
        f"(deposit_ratio={gb_pay.deposit_ratio}, "
        f"commission_rate={gb_pay.commission_rule.rate})"
    )
    assert isinstance(ride_pay, DynamicPricing)
    assert isinstance(gb_pay, InstallmentPayment)

    # ===== 3. 验证 access_rule 隔离 =====
    # 用户只有 business_license，无 driver_license
    gb_user = _DemoUser(user_id="gb_buyer", name="gb_buyer")
    gb_user.metadata["credentials"] = ["business_license"]
    gb_user.metadata["trust_score"] = 5.0

    ride_task = CustomTask(demander_id="gb_buyer", domain_tag=DomainTag.of("ride"))
    gb_task = CustomTask(
        demander_id="gb_buyer", domain_tag=DomainTag.of("group_buying")
    )

    ride_access = server.rule_engine.check_access(gb_user, ride_task)
    gb_access = server.rule_engine.check_access(gb_user, gb_task)

    print(f"\n[4] access_rule 隔离:")
    print(f"    用户 credentials=['business_license'], trust_score=5.0")
    print(f"    ride task 访问检查: {ride_access} (应 False，缺 driver_license)")
    print(f"    group_buying task 访问检查: {gb_access} (应 True)")
    assert ride_access is False
    assert gb_access is True

    # ===== 4. 简化的 ride 完整流程 =====
    from ride_hailing.resources import DriverResource
    from ride_hailing.tasks import RideTask

    passenger = server.auth_provider.authenticate(Credential.phone("13800000002"))
    driver_user = server.auth_provider.authenticate(Credential.phone("13900000003"))
    passenger.switch_role("demander")
    driver_user.switch_role("supplier")
    server.user_repo.save(passenger)
    server.user_repo.save(driver_user)

    driver = DriverResource(
        supplier_id=driver_user.user_id,
        domain_tag=DomainTag.of("ride"),
        current_lat=39.905,
        current_lng=116.408,
    )
    driver.register()
    server.resource_repo.save(driver)

    ride_task_full = RideTask(
        demander_id=passenger.user_id,
        domain_tag=DomainTag.of("ride"),
        origin_lat=39.9042,
        origin_lng=116.4074,
        dest_lat=39.9590,
        dest_lng=116.4518,
        title="多插件 Demo 乘车",
    )
    ride_task_full.bind_event_bus(server.event_bus)
    ride_task_full.publish()
    server.task_repo.save(ride_task_full)

    candidates = server.resource_repo.find_available(DomainTag.of("ride"))
    result = server.match_strategy_for("ride").execute(ride_task_full, candidates)
    print(f"\n[5] ride 完整匹配流程:")
    print(f"    任务: {ride_task_full.title}")
    print(f"    匹配结果: {result.matched}, 司机: {result.selected_resource_id}")
    assert result.matched

    print("\n" + "=" * 60)
    print("Demo 完成：三插件并存，按 domain 路由正确，access_rule 隔离正确")
    print("=" * 60)

    server.stop()


if __name__ == "__main__":
    main()
