"""BrokerAgent 测试。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import TaskStatus
from umcp_core.server import UMCPServer
from group_buying.broker import BrokerAgent
from group_buying.tasks import BuyerTask


def _make_server() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    return server


def _make_buyer_task(category: str, quantity: int, budget_max: float, demander_id: str = "buyer_001") -> BuyerTask:
    return BuyerTask(
        demander_id=demander_id,
        domain_tag=DomainTag.of("group_buying"),
        category=category,
        quantity=quantity,
        budget_max=budget_max,
    )


def test_submit_buyer_task_buffers_by_category():
    """submit_buyer_task 按品类缓冲。"""
    server = _make_server()
    broker = BrokerAgent(server=server, aggregation_threshold=3)
    task1 = _make_buyer_task("空调", 10, 3000.0, "buyer_001")
    task2 = _make_buyer_task("空调", 5, 2800.0, "buyer_002")
    task3 = _make_buyer_task("保洁", 1, 500.0, "buyer_003")

    broker.submit_buyer_task(task1)
    broker.submit_buyer_task(task2)
    broker.submit_buyer_task(task3)

    assert len(broker._buffer["空调"]) == 2
    assert len(broker._buffer["保洁"]) == 1


def test_try_aggregate_returns_none_when_below_threshold():
    """BuyerTask 数量不足阈值时返回 None。"""
    server = _make_server()
    broker = BrokerAgent(server=server, aggregation_threshold=3)
    task1 = _make_buyer_task("空调", 10, 3000.0, "buyer_001")
    task2 = _make_buyer_task("空调", 5, 2800.0, "buyer_002")
    broker.submit_buyer_task(task1)
    broker.submit_buyer_task(task2)

    result = broker.try_aggregate("空调")
    assert result is None


def test_try_aggregate_creates_tender_when_threshold_met():
    """达到阈值时创建 TenderTask。"""
    server = _make_server()
    broker = BrokerAgent(server=server, aggregation_threshold=3)
    tasks = [
        _make_buyer_task("空调", 10, 3000.0, f"buyer_{i}") for i in range(3)
    ]
    for t in tasks:
        broker.submit_buyer_task(t)

    tender = broker.try_aggregate("空调")
    assert tender is not None
    assert tender.custom_fields["category"] == "空调"
    assert tender.custom_fields["total_quantity"] == 30  # 10+10+10
    assert len(tender.custom_fields["buyer_task_ids"]) == 3
    assert tender.demander_id == "broker_001"


def test_try_aggregate_calculates_target_unit_price():
    """目标单价为买家预算的加权平均（按数量加权）。"""
    server = _make_server()
    broker = BrokerAgent(server=server, aggregation_threshold=3)
    # 买家1: 10台×3000元, 买家2: 5台×2800元, 买家3: 15台×3200元
    # 加权平均 = (10*3000 + 5*2800 + 15*3200) / 30 = (30000+14000+48000)/30 = 92000/30 ≈ 3066.67
    broker.submit_buyer_task(_make_buyer_task("空调", 10, 3000.0, "buyer_1"))
    broker.submit_buyer_task(_make_buyer_task("空调", 5, 2800.0, "buyer_2"))
    broker.submit_buyer_task(_make_buyer_task("空调", 15, 3200.0, "buyer_3"))

    tender = broker.try_aggregate("空调")
    assert tender is not None
    expected = round((10 * 3000.0 + 5 * 2800.0 + 15 * 3200.0) / 30, 2)
    assert tender.custom_fields["target_unit_price"] == expected


def test_try_aggregate_independent_categories():
    """不同品类独立聚合。"""
    server = _make_server()
    broker = BrokerAgent(server=server, aggregation_threshold=2)
    broker.submit_buyer_task(_make_buyer_task("空调", 10, 3000.0, "buyer_1"))
    broker.submit_buyer_task(_make_buyer_task("保洁", 1, 500.0, "buyer_2"))
    broker.submit_buyer_task(_make_buyer_task("保洁", 1, 600.0, "buyer_3"))

    # 空调不足阈值
    assert broker.try_aggregate("空调") is None
    # 保洁达到阈值
    tender = broker.try_aggregate("保洁")
    assert tender is not None
    assert tender.custom_fields["category"] == "保洁"


def test_try_aggregate_clears_buffer_after_aggregation():
    """聚合后从缓冲池移除（防重复聚合）。"""
    server = _make_server()
    broker = BrokerAgent(server=server, aggregation_threshold=3)
    for i in range(3):
        broker.submit_buyer_task(_make_buyer_task("空调", 10, 3000.0, f"buyer_{i}"))

    tender1 = broker.try_aggregate("空调")
    assert tender1 is not None

    # 再次聚合应返回 None（缓冲池已清空）
    tender2 = broker.try_aggregate("空调")
    assert tender2 is None


def test_notify_buyers_publishes_event():
    """notify_buyers 通过事件总线发送事件。"""
    server = _make_server()
    broker = BrokerAgent(server=server, aggregation_threshold=3)
    for i in range(3):
        broker.submit_buyer_task(_make_buyer_task("空调", 10, 3000.0, f"buyer_{i}"))

    tender = broker.try_aggregate("空调")
    assert tender is not None

    # 通知买家
    broker.notify_buyers(tender, event_type="tender_published")

    # 事件总线应有记录
    history = server.event_bus.history()
    assert len(history) > 0
    # 最后一个事件应是 tender_published
    last_event = history[-1]
    assert last_event.type.value == "tender_published" or "tender" in str(last_event.type.value).lower()
