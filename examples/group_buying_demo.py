"""集采服务行业插件 demo。

直接运行：python examples/group_buying_demo.py

演示完整交易流程：
1. 加载集采插件
2. 3 个买家认证并提交采购需求
3. BrokerAgent 聚合需求
4. 发起 TenderTask（含商品+服务子任务）
5. 3 个供应商认证并报价
6. 系统自动选标（综合评分）
7. 分期支付托管（订金）
8. 供应商备货 → 扣订金
9. 履约（商品+服务子任务完成）→ 扣尾款
10. 双向评价 + 事件审计
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "plugins"))

from umcp_core.core import Deal, DealStatus, DomainTag, ResourceStatus, TaskStatus
from umcp_core.core.domain import Credential
from umcp_core.layers.l4 import PaymentStatus
from umcp_core.layers.l5 import Evaluation
from umcp_core.server import UMCPServer
from group_buying.broker import BrokerAgent
from group_buying.resources import SupplierResource
from group_buying.tasks import BuyerTask


def main() -> None:
    print("=" * 60)
    print("UMCP 集采服务行业插件 Demo")
    print("=" * 60)

    # 1. 启动服务器并加载插件
    print("\n[1] 启动 UMCP 服务器，加载集采插件...")
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("group_buying")
    server.start()
    print(f"    已加载插件: {[p.name for p in server.plugins]}")
    print(f"    匹配策略: {type(server.match_strategy).__name__}")
    print(f"    支付模式: {type(server.payment_schema).__name__}")

    # 2. 3 个买家认证并提交需求
    print("\n[2] 3 个买家认证并提交采购需求...")
    broker = BrokerAgent(server=server, aggregation_threshold=3)
    buyers = []
    for i in range(1, 4):
        user = server.auth_provider.authenticate(Credential.phone(f"1380000000{i:02d}"))
        user.switch_role("demander")
        server.user_repo.save(user)
        buyers.append(user)

        task = BuyerTask(
            demander_id=user.user_id,
            domain_tag=DomainTag.of("group_buying"),
            category="空调",
            quantity=10,
            budget_max=3000.0,
            spec_requirements=["1.5匹", "变频"],
        )
        broker.submit_buyer_task(task)
        print(f"    买家{i}: {user.user_id} 提交需求（10台空调，预算3000元/台）")

    # 3. 聚合
    print("\n[3] BrokerAgent 聚合需求...")
    tender = broker.try_aggregate("空调")
    print(f"    聚合成功！TenderTask ID: {tender.task_id}")
    print(f"    总数量: {tender.custom_fields['total_quantity']} 台")
    print(f"    目标单价: {tender.custom_fields['target_unit_price']} 元")
    print(f"    参团买家数: {len(tender.custom_fields['buyer_task_ids'])}")

    # 4. 发起招标
    print("\n[4] 发起 TenderTask（含商品+服务子任务）...")
    tender.bind_event_bus(server.event_bus)
    tender.publish()
    server.task_repo.save(tender)
    print(f"    任务状态: {tender.status}")
    print(f"    商品子任务: {tender.standard_sub_tasks[0].task_id}")
    print(f"    服务子任务: {tender.custom_sub_task.task_id}")

    # 5. 3 个供应商报价
    print("\n[5] 3 个供应商报价...")
    suppliers = []
    bids = [
        ("供应商A", 2800.0, 5, 4.5),  # 价格中、交期中、信誉高
        ("供应商B", 2900.0, 3, 4.0),  # 价格高、交期短、信誉中
        ("供应商C", 2700.0, 7, 3.5),  # 价格低、交期长、信誉低
    ]
    for i, (name, price, delivery, trust) in enumerate(bids, 1):
        su = server.auth_provider.authenticate(Credential.phone(f"1390000000{i:02d}"))
        su.switch_role("supplier")
        server.user_repo.save(su)

        supplier = SupplierResource(
            supplier_id=su.user_id,
            domain_tag=DomainTag.of("group_buying"),
            supplier_name=name,
            product_sku="AC-1.5P-GREE",
            service_capability=["delivery", "installation"],
            trust_score=trust,
        )
        supplier.metadata["bid"] = {"price": price, "delivery_days": delivery}
        supplier.register()
        server.resource_repo.save(supplier)
        suppliers.append((su, supplier))
        print(f"    {name}: 报价 {price} 元/台, 交期 {delivery} 天, 信誉 {trust}")

    # 设置 bid 范围（供评分器归一化）
    prices = [b[1] for b in bids]
    deliveries = [b[2] for b in bids]
    tender.custom_fields["bid_price_range"] = (min(prices), max(prices))
    tender.custom_fields["bid_delivery_range"] = (min(deliveries), max(deliveries))

    # 6. 系统选标
    print("\n[6] 系统自动选标（综合评分：价格0.5 + 交期0.3 + 信誉0.2）...")
    candidates = [s for _, s in suppliers]
    result = server.match_strategy.execute(tender, candidates)
    winner = next(s for _, s in suppliers if s.resource_id == result.selected_resource_id)
    winner_user = next(su for su, s in suppliers if s.resource_id == result.selected_resource_id)
    print(f"    中标供应商: {winner.metadata['supplier_name']}")
    print(f"    中标报价: {winner.metadata['bid']['price']} 元/台")

    tender.assign_to(winner.resource_id)
    print(f"    任务状态: {tender.status}")

    # 7. 分期支付托管
    print("\n[7] 创建订单 + 分期支付托管（30% 订金）...")
    total_amount = tender.custom_fields["target_unit_price"] * tender.custom_fields["total_quantity"]
    deal = Deal(
        task_id=tender.task_id,
        resource_id=winner.resource_id,
        demander_id=tender.demander_id,
        supplier_id=winner_user.user_id,
        final_amount=total_amount,
    )
    deal.activate()
    server.deal_repo.save(deal)

    order = server.payment_schema.calculate(tender, deal)
    print(f"    订单总额: {order.total_amount} 元")
    print(f"    订金（30%）: {order.metadata['deposit_amount']} 元")
    print(f"    尾款（70%）: {order.metadata['balance_amount']} 元")
    print(f"    平台抽成（5%）: {order.commission} 元")
    print(f"    供应商所得: {order.supplier_amount} 元")

    server.payment_schema.hold_deposit(order)
    print(f"    订金已托管, 支付状态: {order.status}")

    # 8. 供应商备货 → 扣订金
    print("\n[8] 供应商备货 → 扣订金...")
    server.payment_schema.capture_deposit(order)
    print(f"    订金已扣, deposit_status: {order.metadata['deposit_status']}")
    print(f"    订单状态: {order.status}（等待尾款结算）")

    # 9. 履约
    print("\n[9] 履约（商品+服务子任务完成）→ 扣尾款...")
    tender.start_execution()
    print(f"    TenderTask 状态: {tender.status}")

    # 商品子任务
    product_sub = tender.standard_sub_tasks[0]
    product_sub.publish()  # DRAFT → MATCHING（修正：原计划代码遗漏）
    product_sub.assign_to(winner.resource_id)
    product_sub.start_execution()
    print(f"    商品子任务: 配送中...")
    product_sub.complete()
    print(f"    商品子任务: 已完成")

    # 服务子任务
    service_sub = tender.custom_sub_task
    service_sub.publish()  # DRAFT → MATCHING（修正：原计划代码遗漏）
    service_sub.assign_to(winner.resource_id)
    service_sub.start_execution()
    print(f"    服务子任务: 安装中...")
    service_sub.complete()
    print(f"    服务子任务: 已完成")

    # TenderTask 完成
    tender.complete()
    print(f"    TenderTask 状态: {tender.status}")

    # 扣尾款
    server.payment_schema.capture_balance(order)
    print(f"    尾款已扣, balance_status: {order.metadata['balance_status']}")
    print(f"    订单状态: {order.status}")

    # Deal 完成
    deal.complete()
    print(f"    Deal 状态: {deal.status}")

    # 10. 双向评价 + 事件审计
    print("\n[10] 双向评价 + 事件审计...")
    for buyer in buyers:
        eval_ = Evaluation(
            evaluator_id=buyer.user_id,
            evaluatee_id=winner_user.user_id,
            task_id=tender.task_id,
            ratings={
                "delivery": 5.0,
                "quality": 4.5,
                "service": 5.0,
                "cost_performance": 4.0,
            },
            comment="履约顺利",
        )
        server.trust_engine.record_evaluation(eval_)

    profile = server.trust_engine.evaluate(winner_user.user_id)
    print(f"    中标供应商信誉画像:")
    for dim, score in profile.dimension_scores.items():
        print(f"      {dim}: {score}")
    print(f"      综合分: {profile.overall_score:.2f}")

    # 事件审计
    print(f"\n    事件审计日志（共 {len(server.event_bus.history())} 条）:")
    for event in server.event_bus.history():
        print(f"      [{event.source_layer}] {event.type.value} | {event.payload}")

    print("\n" + "=" * 60)
    print("Demo 完成。集采服务全流程跑通。")
    print("=" * 60)

    server.stop()


if __name__ == "__main__":
    main()
