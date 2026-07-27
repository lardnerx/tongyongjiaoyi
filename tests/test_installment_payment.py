"""InstallmentPayment 分期付款策略测试。"""
from __future__ import annotations

import pytest

from umcp_core.core.deal import Deal
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import Task
from umcp_core.layers.l4 import (
    FlatCommissionRule,
    InstallmentPayment,
    PaymentStatus,
)


class _Task(Task):
    def task_type(self) -> str:
        return "test"


def _make_task_and_deal(total: float = 1000.0) -> tuple[_Task, Deal]:
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    task.custom_fields["total_price"] = total
    deal = Deal(
        task_id=task.task_id,
        resource_id="res_1",
        demander_id="u1",
        supplier_id="s1",
        final_amount=total,
    )
    return task, deal


def test_calculate_splits_deposit_and_balance():
    """calculate 正确拆分订金和尾款。"""
    payment = InstallmentPayment(deposit_ratio=0.3, commission_rule=FlatCommissionRule(rate=0.05))
    task, deal = _make_task_and_deal(total=1000.0)
    order = payment.calculate(task, deal)
    assert order.total_amount == 1000.0
    assert order.metadata["deposit_amount"] == 300.0
    assert order.metadata["balance_amount"] == 700.0
    assert order.metadata["deposit_status"] == "none"
    assert order.metadata["balance_status"] == "none"
    assert order.commission == 50.0  # 5% of 1000
    assert order.supplier_amount == 950.0


def test_hold_deposit_transitions_status():
    """hold_deposit 将订金状态设为 held，订单状态设为 HELD。"""
    payment = InstallmentPayment(deposit_ratio=0.3)
    task, deal = _make_task_and_deal()
    order = payment.calculate(task, deal)
    payment.hold_deposit(order)
    assert order.metadata["deposit_status"] == "held"
    assert order.status == PaymentStatus.HELD


def test_capture_deposit_transitions_status():
    """capture_deposit 将订金状态设为 captured，订单仍 HELD。"""
    payment = InstallmentPayment(deposit_ratio=0.3)
    task, deal = _make_task_and_deal()
    order = payment.calculate(task, deal)
    payment.hold_deposit(order)
    payment.capture_deposit(order)
    assert order.metadata["deposit_status"] == "captured"
    assert order.status == PaymentStatus.HELD  # 订单整体仍 HELD


def test_capture_balance_transitions_to_captured():
    """capture_balance 将尾款状态设为 captured，订单状态设为 CAPTURED。"""
    payment = InstallmentPayment(deposit_ratio=0.3)
    task, deal = _make_task_and_deal()
    order = payment.calculate(task, deal)
    payment.hold_deposit(order)
    payment.capture_deposit(order)
    payment.capture_balance(order)
    assert order.metadata["balance_status"] == "captured"
    assert order.status == PaymentStatus.CAPTURED


def test_capture_deposit_without_hold_raises():
    """未托管直接扣订金抛 RuntimeError。"""
    payment = InstallmentPayment(deposit_ratio=0.3)
    task, deal = _make_task_and_deal()
    order = payment.calculate(task, deal)
    with pytest.raises(RuntimeError, match="订金未托管"):
        payment.capture_deposit(order)


def test_capture_balance_without_deposit_capture_raises():
    """未扣订金直接扣尾款抛 RuntimeError。"""
    payment = InstallmentPayment(deposit_ratio=0.3)
    task, deal = _make_task_and_deal()
    order = payment.calculate(task, deal)
    with pytest.raises(RuntimeError, match="订金未扣"):
        payment.capture_balance(order)

    payment.hold_deposit(order)
    with pytest.raises(RuntimeError, match="订金未扣"):
        payment.capture_balance(order)


def test_commission_calculation():
    """抽成按全款计算，非按订金。"""
    payment = InstallmentPayment(deposit_ratio=0.3, commission_rule=FlatCommissionRule(rate=0.10))
    task, deal = _make_task_and_deal(total=2000.0)
    order = payment.calculate(task, deal)
    assert order.commission == 200.0  # 10% of 2000
    assert order.supplier_amount == 1800.0


def test_deposit_ratio_boundary():
    """deposit_ratio=1.0 时全款为订金，0.0 时无订金。"""
    payment_full = InstallmentPayment(deposit_ratio=1.0)
    task, deal = _make_task_and_deal(total=500.0)
    order = payment_full.calculate(task, deal)
    assert order.metadata["deposit_amount"] == 500.0
    assert order.metadata["balance_amount"] == 0.0

    payment_zero = InstallmentPayment(deposit_ratio=0.0)
    order2 = payment_zero.calculate(task, deal)
    assert order2.metadata["deposit_amount"] == 0.0
    assert order2.metadata["balance_amount"] == 500.0


def test_hold_capture_refund_implement_abstract_methods():
    """InstallmentPayment 实现了 PaymentSchema 的 4 个抽象方法。"""
    payment = InstallmentPayment(deposit_ratio=0.3)
    task, deal = _make_task_and_deal()
    order = payment.calculate(task, deal)

    # hold 委托 hold_deposit
    payment.hold(order)
    assert order.metadata["deposit_status"] == "held"

    # capture 调用 capture_deposit + capture_balance
    payment.capture(order)
    assert order.metadata["deposit_status"] == "captured"
    assert order.metadata["balance_status"] == "captured"
    assert order.status == PaymentStatus.CAPTURED

    # refund 重置状态
    payment.refund(order)
    assert order.status == PaymentStatus.REFUNDED
