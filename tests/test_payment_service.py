"""支付服务测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def mock_gateway():
    from umcp_core.shared.payment.mock import MockGateway
    return MockGateway()


def test_mock_gateway_create_payment_returns_intent(mock_gateway):
    from umcp_core.shared.payment.base import PaymentType
    intent = mock_gateway.create_payment(
        deal_id="deal_1", amount=100.0, payment_type=PaymentType.DEPOSIT
    )
    assert intent.payment_id
    assert intent.amount == 100.0
    assert intent.deal_id == "deal_1"
    assert intent.payment_type == PaymentType.DEPOSIT
    assert intent.client_secret  # 非空


def test_mock_gateway_query_payment_returns_paid(mock_gateway):
    from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
    intent = mock_gateway.create_payment(
        deal_id="deal_1", amount=100.0, payment_type=PaymentType.DEPOSIT
    )
    status = mock_gateway.query_payment(intent.payment_id)
    assert status.status == PaymentStatusEnum.PAID
    assert status.trade_no


def test_mock_gateway_refund_succeeds(mock_gateway):
    from umcp_core.shared.payment.base import PaymentType
    intent = mock_gateway.create_payment(
        deal_id="deal_1", amount=100.0, payment_type=PaymentType.DEPOSIT
    )
    result = mock_gateway.refund(intent.payment_id, amount=50.0, reason="test")
    assert result.success is True
    assert result.refund_amount == 50.0


def test_mock_gateway_handle_callback_returns_result(mock_gateway):
    result = mock_gateway.handle_callback(b"mock_callback_data")
    assert result["status"] == "paid"


def test_in_memory_payment_repo_save_and_find():
    from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    repo = InMemoryPaymentRepository()
    repo.save(
        payment_id="pay_1",
        deal_id="deal_1",
        user_id="u_1",
        amount=100.0,
        payment_type=PaymentType.DEPOSIT,
        status=PaymentStatusEnum.PAID,
        gateway="MOCK",
        trade_no="t_1",
    )
    p = repo.find_by_id("pay_1")
    assert p is not None
    assert p["payment_id"] == "pay_1"
    assert p["amount"] == 100.0
    assert p["status"] == PaymentStatusEnum.PAID.value


def test_in_memory_payment_repo_find_by_deal():
    from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    repo = InMemoryPaymentRepository()
    repo.save("pay_1", "deal_1", "u_1", 30.0, PaymentType.DEPOSIT, PaymentStatusEnum.PAID, "MOCK", "t_1")
    repo.save("pay_2", "deal_1", "u_1", 70.0, PaymentType.BALANCE, PaymentStatusEnum.PENDING, "MOCK", "t_2")
    items = repo.find_by_deal("deal_1")
    assert len(items) == 2


@pytest.fixture
def payment_service():
    from umcp_core.events.bus import EventBus
    from umcp_core.shared.payment.mock import MockGateway
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    from umcp_core.shared.payment.service import PaymentService
    return PaymentService(
        gateway=MockGateway(),
        repo=InMemoryPaymentRepository(),
        event_bus=EventBus(),
    )


def test_payment_service_create_payment_persists_and_returns_intent(payment_service):
    from umcp_core.shared.payment.base import PaymentType
    intent = payment_service.create_payment(
        deal_id="deal_1",
        user_id="u_1",
        amount=30.0,
        payment_type=PaymentType.DEPOSIT,
    )
    assert intent.payment_id
    persisted = payment_service.repo.find_by_id(intent.payment_id)
    assert persisted is not None
    assert persisted["amount"] == 30.0


def test_payment_service_confirm_payment_updates_status_and_emits_event(payment_service):
    from umcp_core.events.types import EventType
    from umcp_core.shared.payment.base import PaymentType
    received = []
    payment_service._event_bus.subscribe(EventType.PAYMENT_PAID, lambda e: received.append(e))

    intent = payment_service.create_payment("deal_1", "u_1", 30.0, PaymentType.DEPOSIT)
    payment_service.confirm_payment(intent.payment_id, trade_no="trade_x")

    persisted = payment_service.repo.find_by_id(intent.payment_id)
    from umcp_core.shared.payment.base import PaymentStatusEnum
    assert persisted["status"] == PaymentStatusEnum.PAID.value
    assert persisted["trade_no"] == "trade_x"
    assert len(received) == 1
    assert received[0].type == EventType.PAYMENT_PAID
    assert received[0].payload["payment_id"] == intent.payment_id


def test_payment_service_refund_emits_event(payment_service):
    from umcp_core.events.types import EventType
    from umcp_core.shared.payment.base import PaymentType
    refund_events = []
    payment_service._event_bus.subscribe(EventType.PAYMENT_REFUNDED, lambda e: refund_events.append(e))

    intent = payment_service.create_payment("deal_1", "u_1", 100.0, PaymentType.FULL)
    payment_service.confirm_payment(intent.payment_id, trade_no="t1")
    payment_service.refund(intent.payment_id, amount=50.0, reason="test")

    assert len(refund_events) == 1
