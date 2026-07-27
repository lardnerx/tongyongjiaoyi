"""集采虚拟中间人：聚合 BuyerTask → 发起 TenderTask。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import CustomTask, StandardTask
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from group_buying.tasks import BuyerTask, TenderTask

if TYPE_CHECKING:
    from umcp_core.server import UMCPServer


class BrokerAgent:
    """虚拟中间人：聚合 BuyerTask → 发起 TenderTask。

    职责：
    1. 接收同品类 BuyerTask，按品类缓冲聚合
    2. 聚合数量达到阈值后创建 TenderTask
    3. 通知所有参团买家招标进展

    设计要点：
    - 通过显式调用 submit_buyer_task + try_aggregate 工作（便于测试）
    - broker_user_id 作为 TenderTask 的 demander_id
    - 同品类累积达到 aggregation_threshold 时才能聚合
    - 聚合后该批 BuyerTask 从缓冲池移除（防重复）
    - 不同品类独立缓冲池
    """

    def __init__(
        self,
        server: "UMCPServer",
        broker_user_id: str = "broker_001",
        aggregation_threshold: int = 3,
    ) -> None:
        self._server = server
        self._broker_user_id: str = broker_user_id
        self._aggregation_threshold: int = aggregation_threshold
        self._buffer: dict[str, list[BuyerTask]] = {}

    def submit_buyer_task(self, task: BuyerTask) -> None:
        """接收买家需求意向，按品类缓冲聚合。"""
        category = task.custom_fields["category"]
        if category not in self._buffer:
            self._buffer[category] = []
        self._buffer[category].append(task)

    def try_aggregate(self, category: str) -> TenderTask | None:
        """尝试聚合指定品类的待处理需求。

        达到阈值时创建 TenderTask 并从缓冲池移除该批 BuyerTask。
        不足阈值时返回 None。
        """
        pending = self._buffer.get(category, [])
        if len(pending) < self._aggregation_threshold:
            return None

        # 取出该批 BuyerTask
        batch = pending[: self._aggregation_threshold]
        self._buffer[category] = pending[self._aggregation_threshold:]

        # 计算聚合数量
        total_quantity = sum(t.custom_fields["quantity"] for t in batch)

        # 计算加权平均预算（按数量加权）
        total_budget = sum(
            t.custom_fields["quantity"] * t.budget_max for t in batch
        )
        target_unit_price = round(total_budget / total_quantity, 2) if total_quantity > 0 else 0.0

        # 创建商品子任务（StandardTask）
        product_sub = StandardTask(
            demander_id=self._broker_user_id,
            domain_tag=DomainTag.of("group_buying"),
        )
        product_sub.custom_fields["sku"] = f"AGG-{category}"
        product_sub.custom_fields["quantity"] = total_quantity

        # 创建服务子任务（CustomTask）
        service_sub = CustomTask(
            demander_id=self._broker_user_id,
            domain_tag=DomainTag.of("group_buying"),
        )
        service_sub.proposal_requirements = ["含配送", "含安装"]

        # 创建 TenderTask
        tender = TenderTask(
            demander_id=self._broker_user_id,
            domain_tag=DomainTag.of("group_buying"),
            category=category,
            total_quantity=total_quantity,
            target_unit_price=target_unit_price,
            buyer_task_ids=[t.task_id for t in batch],
            standard_sub_tasks=[product_sub],
            custom_sub_task=service_sub,
        )

        return tender

    def notify_buyers(self, tender: TenderTask, event_type: str) -> None:
        """通知所有参团买家招标进展。"""
        # 复用 EventType 已有事件，无法解析时用 TASK_PUBLISHED 作为招标通知的兜底
        try:
            evt_type = EventType(event_type)
        except ValueError:
            evt_type = EventType.TASK_PUBLISHED

        event = Event(
            type=evt_type,
            source_layer="L2",
            payload={
                "tender_id": tender.task_id,
                "category": tender.custom_fields["category"],
                "buyer_task_ids": tender.custom_fields["buyer_task_ids"],
            },
        )
        self._server.event_bus.publish(event)
