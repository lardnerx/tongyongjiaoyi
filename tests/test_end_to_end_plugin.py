"""基于插件的端到端测试：通过 load_plugin 加载网约车插件，跑通完整交易流程。

对应 CodeWiki.md 6.7 节阶段一单行业验证清单。
"""

from __future__ import annotations

import pytest

from umcp_core.core import DealStatus, DomainTag, ResourceStatus, TaskStatus
from umcp_core.core.domain import Credential
from umcp_core.events import EventType
from umcp_core.server import UMCPServer
from ride_hailing.resources import DriverResource
from ride_hailing.tasks import RideTask


class TestEndToEndWithPlugin:
    """完整交易流程：认证 → 发单 → 匹配 → 支付 → 评价。"""

    @pytest.fixture
    def server(self) -> UMCPServer:
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.load_plugin("ride_hailing")
        server.start()
        return server

    def test_full_ride_hailing_flow(self, server: UMCPServer):
        # ===== L1 认证 =====
        passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
        driver_user = server.auth_provider.authenticate(Credential.phone("13900000002"))
        passenger.switch_role("demander")
        driver_user.switch_role("supplier")
        server.user_repo.save(passenger)
        server.user_repo.save(driver_user)

        # ===== L2 资源上线：司机出车 =====
        driver = DriverResource(
            supplier_id=driver_user.user_id,
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,  # 靠近乘客起点
            current_lng=116.408,
            plate_number="京A12345",
        )
        driver.register()
        server.resource_repo.save(driver)
        assert driver.status == ResourceStatus.IDLE

        # ===== L2 任务发布：乘客发单 =====
        task = RideTask(
            demander_id=passenger.user_id,
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
            title="从天安门到鸟巢",
        )
        task.bind_event_bus(server.event_bus)
        task.publish()
        server.task_repo.save(task)
        assert task.status == TaskStatus.MATCHING
        assert task.custom_fields["base_price"] > 0

        # ===== L3 匹配：系统派单 =====
        candidates = server.resource_repo.find_available(DomainTag.of("ride"))
        assert len(candidates) == 1
        result = server.match_strategy.execute(task, candidates)
        assert result.matched
        assert result.selected_resource_id == driver.resource_id

        task.assign_to(driver.resource_id)
        assert task.status == TaskStatus.ASSIGNED

        # ===== L4 支付：预估 + 托管 =====
        from umcp_core.core import Deal

        deal = Deal(
            task_id=task.task_id,
            resource_id=driver.resource_id,
            demander_id=passenger.user_id,
            supplier_id=driver_user.user_id,
            final_amount=task.custom_fields["base_price"],
        )
        deal.activate()
        server.deal_repo.save(deal)

        order = server.payment_schema.calculate(task, deal)
        assert order.total_amount > 0
        assert order.commission == round(order.total_amount * 0.20, 2)
        server.payment_schema.hold(order)
        from umcp_core.layers.l4 import PaymentStatus

        assert order.status == PaymentStatus.HELD

        # ===== 服务执行与完成 =====
        task.start_execution()
        driver.update_status(ResourceStatus.BUSY)

        task.complete()
        deal.complete()
        server.payment_schema.capture(order)

        assert task.status == TaskStatus.COMPLETED
        assert deal.status == DealStatus.COMPLETED
        assert order.status == PaymentStatus.CAPTURED

        # ===== L5 评价：双方互评 =====
        from umcp_core.layers.l5 import Evaluation

        passenger_eval = Evaluation(
            evaluator_id=passenger.user_id,
            evaluatee_id=driver_user.user_id,
            task_id=task.task_id,
            ratings={
                "punctuality": 5.0,
                "cleanliness": 4.0,
                "driving_smoothness": 5.0,
                "communication": 4.0,
            },
            comment="很顺利",
        )
        server.trust_engine.record_evaluation(passenger_eval)

        driver_profile = server.trust_engine.evaluate(driver_user.user_id)
        assert driver_profile.get_score("punctuality") == 5.0
        assert driver_profile.get_score("cleanliness") == 4.0

        # ===== 事件总线审计 =====
        history = server.event_bus.history()
        event_types = [e.type for e in history]
        assert EventType.TASK_PUBLISHED in event_types
        assert EventType.TASK_ASSIGNED in event_types
        assert EventType.TASK_COMPLETED in event_types

    def test_multiple_drivers_nearest_wins(self, server: UMCPServer):
        """多个司机时，最近的司机应被优先匹配。"""
        passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
        passenger.switch_role("demander")
        server.user_repo.save(passenger)

        # 三个司机，距离不同
        near_driver = DriverResource(
            supplier_id="s_near",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,
            current_lng=116.408,
        )
        mid_driver = DriverResource(
            supplier_id="s_mid",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.92,
            current_lng=116.42,
        )
        far_driver = DriverResource(
            supplier_id="s_far",
            domain_tag=DomainTag.of("ride"),
            current_lat=40.0,
            current_lng=116.5,
        )
        for d in [near_driver, mid_driver, far_driver]:
            d.register()
            server.resource_repo.save(d)

        task = RideTask(
            demander_id=passenger.user_id,
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        task.publish()

        candidates = server.resource_repo.find_available(DomainTag.of("ride"))
        result = server.match_strategy.execute(task, candidates)

        assert result.matched
        assert result.selected_resource_id == near_driver.resource_id

    def test_driver_without_license_filtered_out(self, server: UMCPServer):
        """无 driver_license 的司机应被过滤。"""
        from umcp_core.core import Capability

        passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
        passenger.switch_role("demander")

        # 无驾照的司机（不通过 DriverResource 默认构造，手动去掉能力）
        unlicensed_driver = DriverResource(
            supplier_id="s_unlicensed",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,
            current_lng=116.408,
            capabilities=[],  # 无任何能力
        )
        unlicensed_driver.register()
        server.resource_repo.save(unlicensed_driver)

        task = RideTask(
            demander_id=passenger.user_id,
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        task.publish()

        candidates = server.resource_repo.find_available(DomainTag.of("ride"))
        result = server.match_strategy.execute(task, candidates)

        # 无驾照司机被过滤，匹配失败
        assert not result.matched
