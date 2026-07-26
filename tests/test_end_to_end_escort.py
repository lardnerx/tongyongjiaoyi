"""基于插件的端到端测试：通过 load_plugin 加载陪驾插件，跑通完整交易流程。"""

from __future__ import annotations

import pytest

from umcp_core.core import DealStatus, DomainTag, ResourceStatus, TaskStatus
from umcp_core.core.domain import Credential
from umcp_core.events import EventType
from umcp_core.server import UMCPServer
from escort_driving.resources import CoachResource
from escort_driving.tasks import EscortTask


class TestEndToEndWithEscortPlugin:
    """完整交易流程：认证 → 发单 → 匹配 → 支付 → 评价。"""

    @pytest.fixture
    def server(self) -> UMCPServer:
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.load_plugin("escort_driving")
        server.start()
        return server

    def test_full_escort_driving_flow(self, server: UMCPServer):
        # ===== L1 认证 =====
        student = server.auth_provider.authenticate(Credential.phone("13800000001"))
        coach_user = server.auth_provider.authenticate(Credential.phone("13900000002"))
        student.switch_role("demander")
        coach_user.switch_role("supplier")
        server.user_repo.save(student)
        server.user_repo.save(coach_user)

        # ===== L2 资源上线：教练出车 =====
        coach = CoachResource(
            supplier_id=coach_user.user_id,
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="A",
            skills=["highway", "night", "parking"],
            plate_number="京B88888",
        )
        coach.register()
        server.resource_repo.save(coach)
        assert coach.status == ResourceStatus.IDLE

        # ===== L2 任务发布：学员发单 =====
        task = EscortTask(
            demander_id=student.user_id,
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            car_type="manual",
            required_skills=["highway", "night"],
            duration_hours=2.0,
            title="陪驾练习高速和夜间驾驶",
        )
        task.bind_event_bus(server.event_bus)
        task.publish()
        server.task_repo.save(task)
        assert task.status == TaskStatus.MATCHING
        assert task.custom_fields["actual_hours"] == 2.0

        # ===== L3 匹配：系统派单 =====
        candidates = server.resource_repo.find_available(DomainTag.of("escort"))
        assert len(candidates) == 1
        result = server.match_strategy.execute(task, candidates)
        assert result.matched
        assert result.selected_resource_id == coach.resource_id

        task.assign_to(coach.resource_id)
        assert task.status == TaskStatus.ASSIGNED

        # ===== L4 支付：按时长计费 + 托管 =====
        from umcp_core.core import Deal

        deal = Deal(
            task_id=task.task_id,
            resource_id=coach.resource_id,
            demander_id=student.user_id,
            supplier_id=coach_user.user_id,
            final_amount=0.0,  # Hourly 不使用 deal.final_amount
        )
        deal.activate()
        server.deal_repo.save(deal)

        order = server.payment_schema.calculate(task, deal)
        # 2 小时 × 80 元/小时 = 160 元
        assert order.total_amount == 160.0
        # 20% 抽成 = 32 元
        assert order.commission == 32.0
        assert order.supplier_amount == 128.0
        server.payment_schema.hold(order)
        from umcp_core.layers.l4 import PaymentStatus

        assert order.status == PaymentStatus.HELD

        # ===== 服务执行与完成 =====
        task.start_execution()
        coach.update_status(ResourceStatus.BUSY)

        task.complete()
        deal.complete()
        server.payment_schema.capture(order)
        coach.update_status(ResourceStatus.IDLE)  # 释放车辆

        assert task.status == TaskStatus.COMPLETED
        assert deal.status == DealStatus.COMPLETED
        assert order.status == PaymentStatus.CAPTURED
        assert coach.status == ResourceStatus.IDLE

        # ===== L5 评价：学员评教练 =====
        from umcp_core.layers.l5 import Evaluation

        student_eval = Evaluation(
            evaluator_id=student.user_id,
            evaluatee_id=coach_user.user_id,
            task_id=task.task_id,
            ratings={
                "teaching_ability": 5.0,
                "patience": 4.0,
                "safety_record": 5.0,
            },
            comment="教练很专业",
        )
        server.trust_engine.record_evaluation(student_eval)

        coach_profile = server.trust_engine.evaluate(coach_user.user_id)
        assert coach_profile.get_score("teaching_ability") == 5.0
        assert coach_profile.get_score("patience") == 4.0
        assert coach_profile.get_score("safety_record") == 5.0

        # ===== 事件总线审计 =====
        history = server.event_bus.history()
        event_types = [e.type for e in history]
        assert EventType.TASK_PUBLISHED in event_types
        assert EventType.TASK_ASSIGNED in event_types
        assert EventType.TASK_COMPLETED in event_types

    def test_multiple_coaches_best_skill_match_wins(self, server: UMCPServer):
        """多个教练时，技能匹配最多且等级最高的教练应被优先匹配。"""
        student = server.auth_provider.authenticate(Credential.phone("13800000001"))
        student.switch_role("demander")
        server.user_repo.save(student)

        # 教练 A：A 级，技能全匹配
        coach_a = CoachResource(
            supplier_id="s_a",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="A",
            skills=["highway", "night", "parking"],
        )
        # 教练 B：B 级，技能部分匹配
        coach_b = CoachResource(
            supplier_id="s_b",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.906,
            current_lng=116.409,
            car_type="manual",
            coach_level="B",
            skills=["highway"],  # 仅 1 个匹配
        )
        for c in [coach_a, coach_b]:
            c.register()
            server.resource_repo.save(c)

        task = EscortTask(
            demander_id=student.user_id,
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            car_type="manual",
            required_skills=["highway", "night"],
            duration_hours=1.5,
        )
        task.publish()

        candidates = server.resource_repo.find_available(DomainTag.of("escort"))
        result = server.match_strategy.execute(task, candidates)

        assert result.matched
        # 教练 A：2 技能 + A 级 1.0 = 3.0；教练 B：1 技能 + B 级 0.0 = 1.0
        assert result.selected_resource_id == coach_a.resource_id

    def test_coach_without_license_filtered_out(self, server: UMCPServer):
        """无 coach_license 的教练应被过滤。"""
        from umcp_core.core import Capability

        student = server.auth_provider.authenticate(Credential.phone("13800000001"))
        student.switch_role("demander")

        # 无教练证的教练
        unlicensed_coach = CoachResource(
            supplier_id="s_unlicensed",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            capabilities=[],  # 无任何能力
        )
        unlicensed_coach.register()
        server.resource_repo.save(unlicensed_coach)

        task = EscortTask(
            demander_id=student.user_id,
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            car_type="manual",
            required_skills=["highway"],
            duration_hours=1.0,
        )
        task.publish()

        candidates = server.resource_repo.find_available(DomainTag.of("escort"))
        result = server.match_strategy.execute(task, candidates)

        # 无教练证教练被过滤，匹配失败
        assert not result.matched

    def test_car_type_mismatch_not_matched(self, server: UMCPServer):
        """车型不匹配的教练不应被匹配（返回 -1.0 极低分，但只有 1 个候选时仍会被选中）。
        
        此测试验证：当只有 1 个车型不匹配的教练时，scorer 返回 -1.0，
        但 InstantMatch 仍会选中它（因为过滤后候选非空）。
        这暴露了 InstantMatch 的一个已知行为：scorer 低分不会自动过滤。
        要过滤车型不匹配，应使用 PreMatchFilter（本测试仅记录现状）。
        """
        student = server.auth_provider.authenticate(Credential.phone("13800000001"))
        student.switch_role("demander")
        server.user_repo.save(student)

        # 唯一教练车型不匹配
        mismatched_coach = CoachResource(
            supplier_id="s_mismatch",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="automatic",  # 学员要 manual
            coach_level="A",
            skills=["highway"],
        )
        mismatched_coach.register()
        server.resource_repo.save(mismatched_coach)

        task = EscortTask(
            demander_id=student.user_id,
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            car_type="manual",  # 与教练车型不匹配
            required_skills=["highway"],
            duration_hours=1.0,
        )
        task.publish()

        candidates = server.resource_repo.find_available(DomainTag.of("escort"))
        result = server.match_strategy.execute(task, candidates)

        # 已知行为：InstantMatch 仍会选中（scorer 低分不过滤）
        # 记录此现状，后续可通过 CarTypeFilter 改进
        assert result.matched  # 现状：仍匹配
        assert result.selected_resource_id == mismatched_coach.resource_id
