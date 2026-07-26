"""陪驾服务行业插件 demo。

直接运行：python examples/escort_driving_demo.py

演示完整交易流程：
1. 加载陪驾插件
2. 学员与教练认证
3. 教练出车
4. 学员发单（手动挡，高速+夜间技能，2 小时，天安门集合）
5. 系统自动匹配最优教练
6. 按时长计费并托管
7. 服务完成并扣款
8. 双方互评
9. 打印事件审计日志
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将 src 和 plugins 加入 sys.path，使脚本可独立运行
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "plugins"))

from umcp_core.core import Deal, DealStatus, DomainTag, ResourceStatus, TaskStatus
from umcp_core.core.domain import Credential
from umcp_core.events import EventType
from umcp_core.layers.l4 import PaymentStatus
from umcp_core.layers.l5 import Evaluation
from umcp_core.server import UMCPServer
from escort_driving.resources import CoachResource
from escort_driving.tasks import EscortTask


def main() -> None:
    print("=" * 60)
    print("UMCP 陪驾服务行业插件 Demo")
    print("=" * 60)

    # 1. 启动服务器并加载插件
    print("\n[1] 启动 UMCP 服务器，加载陪驾插件...")
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    server.start()
    print(f"    已加载插件: {[p.name for p in server.plugins]}")

    # 2. 认证
    print("\n[2] 用户认证...")
    student = server.auth_provider.authenticate(Credential.phone("13800000001"))
    coach_user = server.auth_provider.authenticate(Credential.phone("13900000002"))
    student.switch_role("demander")
    coach_user.switch_role("supplier")
    print(f"    学员: {student.user_id} (角色: demander)")
    print(f"    教练: {coach_user.user_id} (角色: supplier)")
    server.user_repo.save(student)
    server.user_repo.save(coach_user)

    # 3. 教练出车
    print("\n[3] 教练出车...")
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
    print(f"    教练资源已上线: {coach.resource_id}")
    print(f"    车牌: {coach.metadata['plate_number']}, 等级: {coach.metadata['coach_level']}")
    print(f"    技能: {coach.metadata['skills']}, 状态: {coach.status}")

    # 4. 学员发单
    print("\n[4] 学员发布陪驾需求...")
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
    print(f"    任务 ID: {task.task_id}")
    print(f"    车型需求: {task.structured_fields['car_type']}")
    print(f"    技能需求: {task.structured_fields['required_skills']}")
    print(f"    预期时长: {task.structured_fields['duration_hours']} 小时")
    print(f"    任务状态: {task.status}")

    # 5. 系统匹配
    print("\n[5] 系统自动匹配...")
    candidates = server.resource_repo.find_available(DomainTag.of("escort"))
    result = server.match_strategy.execute(task, candidates)
    print(f"    候选教练数: {len(candidates)}")
    print(f"    匹配结果: {result.selected_resource_id}")
    task.assign_to(coach.resource_id)
    print(f"    任务状态: {task.status}")

    # 6. 支付
    print("\n[6] 按时长计费并托管...")
    deal = Deal(
        task_id=task.task_id,
        resource_id=coach.resource_id,
        demander_id=student.user_id,
        supplier_id=coach_user.user_id,
        final_amount=0.0,
    )
    deal.activate()
    server.deal_repo.save(deal)

    order = server.payment_schema.calculate(task, deal)
    print(f"    计费方式: 按时长计费")
    print(f"    服务时长: {task.custom_fields['actual_hours']} 小时")
    print(f"    时薪: 80.0 元/小时")
    print(f"    订单金额: {order.total_amount} 元")
    print(f"    平台抽成: {order.commission} 元 (20%)")
    print(f"    教练所得: {order.supplier_amount} 元")
    server.payment_schema.hold(order)
    print(f"    支付状态: {order.status}")

    # 7. 服务完成
    print("\n[7] 服务执行与完成...")
    task.start_execution()
    coach.update_status(ResourceStatus.BUSY)
    print(f"    任务状态: {task.status}, 教练状态: {coach.status}")

    task.complete()
    deal.complete()
    server.payment_schema.capture(order)
    coach.update_status(ResourceStatus.IDLE)
    print(f"    任务状态: {task.status}")
    print(f"    交易状态: {deal.status}")
    print(f"    支付状态: {order.status}")
    print(f"    教练状态: {coach.status}")

    # 8. 评价
    print("\n[8] 双方互评...")
    eval_student_to_coach = Evaluation(
        evaluator_id=student.user_id,
        evaluatee_id=coach_user.user_id,
        task_id=task.task_id,
        ratings={
            "teaching_ability": 5.0,
            "patience": 4.0,
            "safety_record": 5.0,
        },
        comment="教练很专业，高速和夜间驾驶讲得很细",
    )
    server.trust_engine.record_evaluation(eval_student_to_coach)

    profile = server.trust_engine.evaluate(coach_user.user_id)
    print(f"    教练信誉画像:")
    for dim, score in profile.dimension_scores.items():
        print(f"      {dim}: {score}")
    print(f"      综合分: {profile.overall_score:.2f}")

    # 9. 事件审计
    print("\n[9] 事件审计日志...")
    history = server.event_bus.history()
    for event in history:
        print(f"    [{event.source_layer}] {event.type.value} | {event.payload}")

    print("\n" + "=" * 60)
    print("Demo 完成。陪驾服务交易流程全部跑通。")
    print("核心库复用：SkillMatchScorer（通用评分器）+ Hourly（通用支付策略）")
    print("=" * 60)

    server.stop()


if __name__ == "__main__":
    main()
