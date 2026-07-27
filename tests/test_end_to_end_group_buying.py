"""集采服务端到端测试：完整交易流程。"""
from __future__ import annotations

import pytest

from umcp_core.core import Deal, DealStatus, DomainTag, TaskStatus
from umcp_core.core.domain import Credential
from umcp_core.layers.l4 import PaymentStatus
from umcp_core.layers.l5 import Evaluation
from umcp_core.server import UMCPServer
from group_buying.broker import BrokerAgent
from group_buying.resources import SupplierResource
from group_buying.tasks import BuyerTask


def _make_server_with_plugin() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("group_buying")
    server.start()
    return server


def _authenticate_buyers(server: UMCPServer, count: int) -> list:
    buyers = []
    for i in range(count):
        user = server.auth_provider.authenticate(Credential.phone(f"1380000000{i+1:02d}"))
        user.switch_role("demander")
        server.user_repo.save(user)
        buyers.append(user)
    return buyers


def _authenticate_supplier(server: UMCPServer, phone: str):
    supplier_user = server.auth_provider.authenticate(Credential.phone(phone))
    supplier_user.switch_role("supplier")
    server.user_repo.save(supplier_user)
    return supplier_user


def _make_buyer_task(buyer_id: str, category: str, quantity: int, budget_max: float) -> BuyerTask:
    task = BuyerTask(
        demander_id=buyer_id,
        domain_tag=DomainTag.of("group_buying"),
        category=category,
        quantity=quantity,
        budget_max=budget_max,
    )
    return task


def _make_supplier_with_bid(
    supplier_user_id: str, price: float, delivery_days: int, trust: float = 4.0,
    service_tags: list[str] | None = None, has_license: bool = True,
) -> SupplierResource:
    caps = None if has_license else []
    supplier = SupplierResource(
        supplier_id=supplier_user_id,
        domain_tag=DomainTag.of("group_buying"),
        supplier_name=f"供应商{supplier_user_id}",
        product_sku="AC-1.5P",
        service_capability=service_tags or ["delivery", "installation"],
        trust_score=trust,
        capabilities=caps,
    )
    supplier.metadata["bid"] = {"price": price, "delivery_days": delivery_days}
    return supplier


def test_full_transaction_flow():
    """完整流程：聚合→招标→报价→选标→分期支付→履约→评价。"""
    server = _make_server_with_plugin()
    try:
        # 1. 认证 3 个买家
        buyers = _authenticate_buyers(server, 3)

        # 2. 创建 BrokerAgent，3 个买家提交需求
        broker = BrokerAgent(server=server, aggregation_threshold=3)
        for buyer in buyers:
            task = _make_buyer_task(buyer.user_id, "空调", 10, 3000.0)
            broker.submit_buyer_task(task)

        # 3. 聚合 → TenderTask
        tender = broker.try_aggregate("空调")
        assert tender is not None
        assert tender.custom_fields["total_quantity"] == 30
        tender.bind_event_bus(server.event_bus)
        tender.publish()
        server.task_repo.save(tender)

        # 4. 3 个供应商报价
        suppliers = []
        for i, (price, delivery, trust) in enumerate([(2800, 5, 4.5), (2900, 3, 4.0), (2700, 7, 3.5)]):
            su = _authenticate_supplier(server, f"1390000000{i+1:02d}")
            supplier = _make_supplier_with_bid(su.user_id, float(price), delivery, trust)
            supplier.register()
            server.resource_repo.save(supplier)
            suppliers.append((su, supplier))

        # 设置 bid 范围（供 CompositeBidScorer 归一化）
        prices = [2800.0, 2900.0, 2700.0]
        deliveries = [5, 3, 7]
        tender.custom_fields["bid_price_range"] = (min(prices), max(prices))
        tender.custom_fields["bid_delivery_range"] = (min(deliveries), max(deliveries))

        # 5. 系统选标
        candidates = [s for _, s in suppliers]
        result = server.match_strategy.execute(tender, candidates)
        assert result.matched
        winner_id = result.selected_resource_id
        winner = next(s for _, s in suppliers if s.resource_id == winner_id)
        winner_user = next(su for su, s in suppliers if s.resource_id == winner_id)

        # 6. 指派
        tender.assign_to(winner.resource_id)

        # 7. 创建 Deal + 分期支付
        total_amount = tender.custom_fields["target_unit_price"] * tender.custom_fields["total_quantity"]
        deal = Deal(
            task_id=tender.task_id,
            resource_id=winner.resource_id,
            demander_id=tender.demander_id,  # broker
            supplier_id=winner_user.user_id,
            final_amount=total_amount,
        )
        deal.activate()
        server.deal_repo.save(deal)

        order = server.payment_schema.calculate(tender, deal)
        assert order.metadata["deposit_amount"] > 0
        assert order.metadata["balance_amount"] > 0

        # 8. 托管订金
        server.payment_schema.hold_deposit(order)
        assert order.status == PaymentStatus.HELD

        # 9. 供应商备货 → 扣订金
        server.payment_schema.capture_deposit(order)
        assert order.metadata["deposit_status"] == "captured"

        # 10. 履约（子任务完成）
        tender.start_execution()
        for sub in tender.standard_sub_tasks:
            sub.publish()
            sub.assign_to(winner.resource_id)
            sub.start_execution()
            sub.complete()
        tender.custom_sub_task.publish()
        tender.custom_sub_task.assign_to(winner.resource_id)
        tender.custom_sub_task.start_execution()
        tender.custom_sub_task.complete()

        # 11. TenderTask 完成
        tender.complete()
        assert tender.status == TaskStatus.COMPLETED

        # 12. 扣尾款
        server.payment_schema.capture_balance(order)
        assert order.status == PaymentStatus.CAPTURED
        assert order.metadata["balance_status"] == "captured"

        # 13. Deal 完成
        deal.complete()
        assert deal.status == DealStatus.COMPLETED

        # 14. 双向评价
        for buyer in buyers:
            eval_ = Evaluation(
                evaluator_id=buyer.user_id,
                evaluatee_id=winner_user.user_id,
                task_id=tender.task_id,
                ratings={
                    "delivery": 5.0, "quality": 4.0,
                    "service": 5.0, "cost_performance": 4.0,
                },
            )
            server.trust_engine.record_evaluation(eval_)

        profile = server.trust_engine.evaluate(winner_user.user_id)
        assert profile.overall_score > 0
    finally:
        server.stop()


def test_supplier_without_license_filtered_out():
    """无 business_license 的供应商被过滤。"""
    server = _make_server_with_plugin()
    try:
        buyers = _authenticate_buyers(server, 3)
        broker = BrokerAgent(server=server, aggregation_threshold=3)
        for buyer in buyers:
            broker.submit_buyer_task(_make_buyer_task(buyer.user_id, "空调", 10, 3000.0))
        tender = broker.try_aggregate("空调")
        tender.bind_event_bus(server.event_bus)
        tender.publish()

        # 合法供应商
        su1 = _authenticate_supplier(server, "13900000001")
        s1 = _make_supplier_with_bid(su1.user_id, 2800.0, 5, trust=4.0, has_license=True)
        s1.register()
        server.resource_repo.save(s1)

        # 无 license 供应商
        su2 = _authenticate_supplier(server, "13900000002")
        s2 = _make_supplier_with_bid(su2.user_id, 2700.0, 3, trust=4.5, has_license=False)
        s2.register()
        server.resource_repo.save(s2)

        result = server.match_strategy.execute(tender, [s1, s2])
        assert result.matched
        assert result.selected_resource_id == s1.resource_id  # s2 被过滤
    finally:
        server.stop()


def test_aggregation_below_threshold_no_tender():
    """聚合不足时不开标。"""
    server = _make_server_with_plugin()
    try:
        buyers = _authenticate_buyers(server, 2)  # 只有 2 个
        broker = BrokerAgent(server=server, aggregation_threshold=3)
        for buyer in buyers:
            broker.submit_buyer_task(_make_buyer_task(buyer.user_id, "空调", 10, 3000.0))
        tender = broker.try_aggregate("空调")
        assert tender is None
    finally:
        server.stop()


def test_tender_complete_raises_if_subtasks_not_done():
    """子任务未完成时 TenderTask.complete 抛错。"""
    server = _make_server_with_plugin()
    try:
        buyers = _authenticate_buyers(server, 3)
        broker = BrokerAgent(server=server, aggregation_threshold=3)
        for buyer in buyers:
            broker.submit_buyer_task(_make_buyer_task(buyer.user_id, "空调", 10, 3000.0))
        tender = broker.try_aggregate("空调")
        tender.publish()
        tender.assign_to("res_1")
        tender.start_execution()

        with pytest.raises(RuntimeError, match="子任务"):
            tender.complete()
    finally:
        server.stop()


def test_optimal_bid_wins_among_multiple_suppliers():
    """多供应商时最优综合报价中标（按综合分选）。"""
    server = _make_server_with_plugin()
    try:
        buyers = _authenticate_buyers(server, 3)
        broker = BrokerAgent(server=server, aggregation_threshold=3)
        for buyer in buyers:
            broker.submit_buyer_task(_make_buyer_task(buyer.user_id, "空调", 10, 3000.0))
        tender = broker.try_aggregate("空调")
        tender.bind_event_bus(server.event_bus)
        tender.publish()

        # 供应商A：价格最低但交期长、信誉低
        su_a = _authenticate_supplier(server, "13900000001")
        s_a = _make_supplier_with_bid(su_a.user_id, 2600.0, 10, trust=2.0)
        s_a.register()
        server.resource_repo.save(s_a)

        # 供应商B：价格中等但交期短、信誉高（综合应更高）
        su_b = _authenticate_supplier(server, "13900000002")
        s_b = _make_supplier_with_bid(su_b.user_id, 2900.0, 3, trust=5.0)
        s_b.register()
        server.resource_repo.save(s_b)

        prices = [2600.0, 2900.0]
        deliveries = [10, 3]
        tender.custom_fields["bid_price_range"] = (min(prices), max(prices))
        tender.custom_fields["bid_delivery_range"] = (min(deliveries), max(deliveries))

        result = server.match_strategy.execute(tender, [s_a, s_b])
        assert result.matched
        # 验证选中的确实是计算后分高的那个
        from group_buying.scoring import TenderBidScorer
        scorer = TenderBidScorer()
        score_a = scorer(tender, s_a)
        score_b = scorer(tender, s_b)
        expected_winner = s_a if score_a > score_b else s_b
        assert result.selected_resource_id == expected_winner.resource_id
    finally:
        server.stop()
