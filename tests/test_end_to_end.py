"""端到端集成测试：模拟一笔完整交易流程。

对应 CodeWiki.md 6.7 节阶段一单行业验证清单：
- L1 认证：乘客/司机用手机号注册登录，两个角色正常切换
- L2 任务发布：乘客创建行程，RideTask 正确入库和序列化
- L2 资源上线：司机出车，上传位置，DriverResource 状态正确流转
- L3 匹配：乘客发单，系统匹配附近司机，InstantMatch 返回正确司机
- L4 支付：预估费用、托管扣款、完成解冻，资金流正确，抽成计算无误
- L5 评价：双方互评，TrustProfile 分数更新
- 事件总线：所有关键步骤产生事件，事件日志完整可追溯
- 状态机：任务和交易状态正确流转，没有非法跳转
"""

from __future__ import annotations

import pytest

from umcp_core.core import (
    Capability,
    CustomTask,
    Deal,
    DealStatus,
    DomainTag,
    Resource,
    ResourceStatus,
    StandardTask,
    Task,
    TaskStatus,
    User,
)
from umcp_core.core.base import Demander, PermissionSet, Supplier
from umcp_core.core.domain import Credential, SpatioTemporalConstraint
from umcp_core.events import Event, EventType
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.layers.l3 import CredentialFilter, InstantMatch
from umcp_core.layers.l4 import DynamicPricing, FixedPrice, FlatCommissionRule, PaymentStatus
from umcp_core.layers.l5 import Evaluation, WeightedSumTrustEngine
from umcp_core.repositories import InMemoryRepositoryBundle
from umcp_core.server import UMCPServer


# ============================================================================
# 行业插件实现（模拟网约车）
# ============================================================================


class RideTask(StandardTask):
    """网约车行程任务。"""

    _task_type_name = "ride"

    def __init__(self, demander_id, domain_tag, **kwargs):
        spatio = kwargs.pop("spatio_temporal", None) or SpatioTemporalConstraint(
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        super().__init__(demander_id, domain_tag, spatio_temporal=spatio, **kwargs)
        # 用 structured_fields 存储行程特有字段
        self.structured_fields.setdefault("car_type", "economy")
        # 预估价（用于 FixedPrice）
        self.custom_fields.setdefault("price", 35.0)
        self.custom_fields.setdefault("base_price", 30.0)

    def task_type(self) -> str:
        return "ride"


class DriverResource(Resource):
    """司机资源。"""

    def __init__(self, supplier_id, domain_tag, **kwargs):
        capabilities = kwargs.pop("capabilities", None)
        if capabilities is None:
            capabilities = [
                Capability(type="certification", name="driver_license", value="C1", verified=True),
            ]
        super().__init__(supplier_id, domain_tag, capabilities=capabilities, **kwargs)
        self.metadata.setdefault("car_type", "economy")

    def resource_type(self) -> str:
        return "driver"


# ============================================================================
# 端到端测试
# ============================================================================


class TestEndToEndRideHailing:
    """模拟一笔网约车交易从头到尾的完整流程。"""

    @pytest.fixture
    def server(self) -> UMCPServer:
        """搭建带内存仓储的 UMCP 服务器。"""
        server = UMCPServer()
        bundle = server.use_in_memory_repositories()

        # 注册任务类型
        server.register_task_type("ride", RideTask)

        # 注入各层组件（模拟插件加载）
        from umcp_core.layers.l2 import DefaultTaskFactory
        from umcp_core.layers.l3 import InstantMatch
        from umcp_core.layers.l4 import DynamicPricing
        from umcp_core.layers.l5 import WeightedSumTrustEngine

        server.set_match_strategy(InstantMatch())
        server.set_payment_schema(DynamicPricing(surge_factor=1.2))
        server.set_trust_engine(
            WeightedSumTrustEngine(dimensions=["punctuality", "cleanliness", "driving_smoothness", "communication"])
        )

        server.start()
        return server

    def test_full_ride_hailing_flow(self, server: UMCPServer):
        """完整交易流程：认证 → 发单 → 匹配 → 支付 → 评价。"""

        # ===== L1 认证：乘客与司机登录 =====
        auth = server.auth_provider
        passenger = auth.authenticate(Credential.phone("13800000001"))
        driver_user = auth.authenticate(Credential.phone("13900000002"))

        # 两个角色正常切换
        passenger.switch_role("demander")
        driver_user.switch_role("supplier")
        assert passenger.is_demander()
        assert driver_user.is_supplier()

        # 用户入库
        server.user_repo.save(passenger)
        server.user_repo.save(driver_user)

        # ===== L2 资源上线：司机出车 =====
        driver = DriverResource(
            supplier_id=driver_user.user_id,
            domain_tag=DomainTag.of("ride"),
        )
        driver.register()
        server.resource_repo.save(driver)

        assert driver.status == ResourceStatus.IDLE
        assert driver.is_available()

        # ===== L2 任务发布：乘客发单 =====
        task = server.task_factory.create_task(
            task_type="ride",
            demander_id=passenger.user_id,
            domain_tag=DomainTag.of("ride"),
            title="从国贸到三里屯",
        )
        # 绑定事件总线以发布事件
        task.bind_event_bus(server.event_bus)
        task.publish()
        server.task_repo.save(task)

        assert task.status == TaskStatus.MATCHING

        # ===== L3 匹配：系统派单 =====
        candidates = server.resource_repo.find_available(DomainTag.of("ride"))
        assert len(candidates) == 1
        assert candidates[0].resource_id == driver.resource_id

        match_result = server.match_strategy.execute(task, candidates)
        assert match_result.matched
        assert match_result.selected_resource_id == driver.resource_id

        # 任务指派
        task.assign_to(driver.resource_id)
        assert task.status == TaskStatus.ASSIGNED

        # 创建交易记录
        deal = Deal(
            task_id=task.task_id,
            resource_id=driver.resource_id,
            demander_id=passenger.user_id,
            supplier_id=driver_user.user_id,
            final_amount=task.custom_fields["base_price"],
        )
        deal.activate()
        server.deal_repo.save(deal)
        assert deal.status == DealStatus.ACTIVE

        # ===== L4 支付：预估 + 托管 + 扣款 =====
        order = server.payment_schema.calculate(task, deal)
        # 动态定价：30 * 1.2 = 36
        assert order.total_amount == 36.0
        # 抽成 20%: 36 * 0.2 = 7.2
        assert order.commission == 7.2
        assert order.supplier_amount == 28.8

        server.payment_schema.hold(order)
        assert order.status == PaymentStatus.HELD

        # ===== 服务执行 =====
        task.start_execution()
        assert task.status == TaskStatus.IN_PROGRESS

        # 司机状态变更为 BUSY
        driver.update_status(ResourceStatus.BUSY)
        server.resource_repo.update_status(driver.resource_id, ResourceStatus.BUSY)

        # ===== 服务完成 =====
        task.complete()
        assert task.status == TaskStatus.COMPLETED

        deal.complete()
        assert deal.status == DealStatus.COMPLETED

        # 扣款
        server.payment_schema.capture(order)
        assert order.status == PaymentStatus.CAPTURED

        # 司机恢复 IDLE
        driver.update_status(ResourceStatus.IDLE)
        server.resource_repo.update_status(driver.resource_id, ResourceStatus.IDLE)

        # ===== L5 评价：双方互评 =====
        # 乘客评价司机
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

        # 司机评价乘客
        driver_eval = Evaluation(
            evaluator_id=driver_user.user_id,
            evaluatee_id=passenger.user_id,
            task_id=task.task_id,
            ratings={
                "punctuality": 5.0,
                "cleanliness": 5.0,
                "driving_smoothness": 5.0,
                "communication": 5.0,
            },
        )
        server.trust_engine.record_evaluation(driver_eval)

        # 校验信任画像已更新
        driver_profile = server.trust_engine.evaluate(driver_user.user_id)
        assert driver_profile.get_score("punctuality") == 5.0
        assert driver_profile.get_score("cleanliness") == 4.0
        assert driver_profile.overall_score > 0

        passenger_profile = server.trust_engine.evaluate(passenger.user_id)
        assert passenger_profile.get_score("punctuality") == 5.0

        # ===== 事件总线审计：关键事件已发布 =====
        history = server.event_bus.history()
        event_types = [e.type for e in history]

        assert EventType.TASK_PUBLISHED in event_types
        assert EventType.TASK_ASSIGNED in event_types
        assert EventType.TASK_COMPLETED in event_types

        # ===== 事件仓储：事件已落库 =====
        stored_events = server.event_repo.replay(task.task_id)
        assert len(stored_events) >= 3  # 至少 published, assigned, completed

        # ===== 状态机校验：无非法跳转 =====
        # 任务状态序列：DRAFT -> PUBLISHED -> MATCHING -> ASSIGNED -> IN_PROGRESS -> COMPLETED
        assert task.status == TaskStatus.COMPLETED
        assert deal.status == DealStatus.COMPLETED

        # 终态不可再转移
        from umcp_core.fsm import TaskStateMachine

        fsm = TaskStateMachine()
        assert not fsm.can_transition(TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS)

    def test_event_flow_logged_correctly(self, server: UMCPServer):
        """验证事件总线日志完整可追溯。"""
        # 创建并发布一个任务
        task = server.task_factory.create_task(
            task_type="ride",
            demander_id="d_test",
            domain_tag=DomainTag.of("ride"),
        )
        task.bind_event_bus(server.event_bus)
        task.publish()
        server.task_repo.save(task)

        # 事件历史应包含 PUBLISHED
        history = server.event_bus.history()
        types = [e.type for e in history]
        assert EventType.TASK_PUBLISHED in types

        # 找到该任务的事件
        task_events = [e for e in history if e.payload.get("task_id") == task.task_id]
        assert len(task_events) >= 1
        assert all(e.source_layer == "L2" for e in task_events)
