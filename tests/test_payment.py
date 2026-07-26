"""测试 L4 交易与支付层。"""

from __future__ import annotations

import pytest

from umcp_core.core import Deal, DomainTag, StandardTask
from umcp_core.layers.l4 import (
    DynamicPricing,
    FixedPrice,
    FlatCommissionRule,
    FullRefundPolicy,
    Hourly,
    Milestone,
    PaymentOrder,
    PaymentSchema,
    PaymentStatus,
    Prepaid,
)


class _PricedTask(StandardTask):
    def task_type(self) -> str:
        return "priced"


def _make_task_and_deal(price: float = 100.0) -> tuple[_PricedTask, Deal]:
    task = _PricedTask(demander_id="d1", domain_tag=DomainTag.of("test"))
    task.custom_fields["price"] = price
    task.publish()
    deal = Deal(
        task_id=task.task_id,
        resource_id="r1",
        demander_id="d1",
        supplier_id="s1",
        final_amount=price,
    )
    deal.activate()
    return task, deal


class TestFixedPrice:
    def test_calculate_with_default_commission(self):
        task, deal = _make_task_and_deal(100.0)
        schema = FixedPrice()
        order = schema.calculate(task, deal)

        assert order.total_amount == 100.0
        assert order.commission == 20.0  # 默认 20%
        assert order.supplier_amount == 80.0

    def test_hold_capture_refund_flow(self):
        task, deal = _make_task_and_deal(100.0)
        schema = FixedPrice()
        order = schema.calculate(task, deal)

        schema.hold(order)
        assert order.status == PaymentStatus.HELD

        schema.capture(order)
        assert order.status == PaymentStatus.CAPTURED

        schema.refund(order)
        assert order.status == PaymentStatus.REFUNDED

    def test_capture_without_hold_raises(self):
        task, deal = _make_task_and_deal(100.0)
        schema = FixedPrice()
        order = schema.calculate(task, deal)
        with pytest.raises(RuntimeError, match="不允许扣款"):
            schema.capture(order)


class TestDynamicPricing:
    def test_surge_factor_applied(self):
        task, deal = _make_task_and_deal(100.0)
        task.custom_fields["base_price"] = 100.0
        schema = DynamicPricing(surge_factor=1.5)
        order = schema.calculate(task, deal)

        assert order.total_amount == 150.0
        assert order.metadata["surge_factor"] == 1.5
        assert order.metadata["base_price"] == 100.0

    def test_commission_calculated_on_surged_price(self):
        task, deal = _make_task_and_deal(100.0)
        task.custom_fields["base_price"] = 100.0
        schema = DynamicPricing(surge_factor=2.0, commission_rule=FlatCommissionRule(0.10))
        order = schema.calculate(task, deal)

        assert order.total_amount == 200.0
        assert order.commission == 20.0  # 10% of 200
        assert order.supplier_amount == 180.0


class TestPrepaid:
    def test_prepaid_hold_equals_capture(self):
        task, deal = _make_task_and_deal(50.0)
        schema = Prepaid()
        order = schema.calculate(task, deal)

        schema.hold(order)
        assert order.status == PaymentStatus.CAPTURED  # 预付费 hold 即扣款

        # capture 不应再变化
        schema.capture(order)
        assert order.status == PaymentStatus.CAPTURED


class TestMilestone:
    def test_calculate_with_milestones_metadata(self):
        task, deal = _make_task_and_deal(1000.0)
        task.custom_fields["total_price"] = 1000.0
        task.custom_fields["milestones"] = [
            {"name": "deposit", "amount": 300},
            {"name": "delivery", "amount": 700},
        ]
        schema = Milestone()
        order = schema.calculate(task, deal)

        assert order.total_amount == 1000.0
        assert len(order.metadata["milestones"]) == 2


class TestHourly:
    def test_calculate_by_hours_and_rate(self):
        task, deal = _make_task_and_deal(0.0)
        task.custom_fields["actual_hours"] = 3.5
        task.custom_fields["hourly_rate"] = 80.0
        schema = Hourly()
        order = schema.calculate(task, deal)

        assert order.total_amount == 280.0
        assert order.metadata["hours"] == 3.5
        assert order.metadata["rate"] == 80.0


class TestCommissionRule:
    def test_flat_commission_rate(self):
        rule = FlatCommissionRule(0.15)
        assert rule.calculate(None, 100.0) == 15.0

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError, match="抽成比例"):
            FlatCommissionRule(1.5)
