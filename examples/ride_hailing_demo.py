"""网约车行业插件 demo。

直接运行：python examples/ride_hailing_demo.py

演示完整交易流程：
1. 加载网约车插件
2. 乘客与司机认证
3. 司机出车
4. 乘客发单（天安门 → 鸟巢）
5. 系统自动匹配最近司机
6. 预估费用并托管
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
from ride_hailing.resources import DriverResource
from ride_hailing.tasks import RideTask


def main() -> None:
    print("=" * 60)
    print("UMCP 网约车行业插件 Demo")
    print("=" * 60)

    # 1. 启动服务器并加载插件
    print("\n[1] 启动 UMCP 服务器，加载网约车插件...")
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("ride_hailing")
    server.start()
    print(f"    已加载插件: {[p.name for p in server.plugins]}")

    # 2. 认证
    print("\n[2] 用户认证...")
    passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
    driver_user = server.auth_provider.authenticate(Credential.phone("13900000002"))
    passenger.switch_role("demander")
    driver_user.switch_role("supplier")
    print(f"    乘客: {passenger.user_id} (角色: demander)")
    print(f"    司机: {driver_user.user_id} (角色: supplier)")
    server.user_repo.save(passenger)
    server.user_repo.save(driver_user)

    # 3. 司机出车
    print("\n[3] 司机出车...")
    driver = DriverResource(
        supplier_id=driver_user.user_id,
        domain_tag=DomainTag.of("ride"),
        current_lat=39.905,
        current_lng=116.408,
        plate_number="京A12345",
        car_type="economy",
    )
    driver.register()
    server.resource_repo.save(driver)
    print(f"    司机资源已上线: {driver.resource_id}")
    print(f"    车牌: {driver.metadata['plate_number']}, 状态: {driver.status}")

    # 4. 乘客发单
    print("\n[4] 乘客发布行程...")
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
    print(f"    任务 ID: {task.task_id}")
    print(f"    预估距离: {task.structured_fields['estimated_distance_km']} 公里")
    print(f"    预估费用: {task.custom_fields['base_price']} 元")
    print(f"    任务状态: {task.status}")

    # 5. 系统匹配
    print("\n[5] 系统自动匹配...")
    candidates = server.resource_repo.find_available(DomainTag.of("ride"))
    result = server.match_strategy.execute(task, candidates)
    print(f"    候选司机数: {len(candidates)}")
    print(f"    匹配结果: {result.selected_resource_id}")
    task.assign_to(driver.resource_id)
    print(f"    任务状态: {task.status}")

    # 6. 支付
    print("\n[6] 预估费用并托管...")
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
    print(f"    订单金额: {order.total_amount} 元")
    print(f"    平台抽成: {order.commission} 元 (20%)")
    print(f"    司机所得: {order.supplier_amount} 元")
    server.payment_schema.hold(order)
    print(f"    支付状态: {order.status}")

    # 7. 服务完成
    print("\n[7] 服务执行与完成...")
    task.start_execution()
    driver.update_status(ResourceStatus.BUSY)
    print(f"    任务状态: {task.status}, 司机状态: {driver.status}")

    task.complete()
    deal.complete()
    server.payment_schema.capture(order)
    driver.update_status(ResourceStatus.IDLE)
    print(f"    任务状态: {task.status}")
    print(f"    交易状态: {deal.status}")
    print(f"    支付状态: {order.status}")
    print(f"    司机状态: {driver.status}")

    # 8. 评价
    print("\n[8] 双方互评...")
    eval_passenger_to_driver = Evaluation(
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
    server.trust_engine.record_evaluation(eval_passenger_to_driver)

    profile = server.trust_engine.evaluate(driver_user.user_id)
    print(f"    司机信誉画像:")
    for dim, score in profile.dimension_scores.items():
        print(f"      {dim}: {score}")
    print(f"      综合分: {profile.overall_score:.2f}")

    # 9. 事件审计
    print("\n[9] 事件审计日志...")
    history = server.event_bus.history()
    for event in history:
        print(f"    [{event.source_layer}] {event.type.value} | {event.payload}")

    print("\n" + "=" * 60)
    print("Demo 完成。交易流程全部跑通。")
    print("=" * 60)

    server.stop()


if __name__ == "__main__":
    main()
