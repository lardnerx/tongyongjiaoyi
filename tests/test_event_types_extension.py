"""EventType 枚举扩展测试。"""

from __future__ import annotations


def test_event_type_deal_in_service_exists():
    from umcp_core.events.types import EventType
    assert EventType.DEAL_IN_SERVICE.value == "deal.in_service"


def test_event_type_review_submitted_exists():
    from umcp_core.events.types import EventType
    assert EventType.REVIEW_SUBMITTED.value == "review.submitted"


def test_event_type_friend_request_created_exists():
    from umcp_core.events.types import EventType
    assert EventType.FRIEND_REQUEST_CREATED.value == "friend_request.created"


def test_event_type_friend_request_accepted_exists():
    from umcp_core.events.types import EventType
    assert EventType.FRIEND_REQUEST_ACCEPTED.value == "friend_request.accepted"


def test_event_type_check_in_exists():
    from umcp_core.events.types import EventType
    assert EventType.CHECK_IN.value == "check_in"


def test_event_type_check_out_exists():
    from umcp_core.events.types import EventType
    assert EventType.CHECK_OUT.value == "check_out"


def test_event_type_payment_paid_exists():
    from umcp_core.events.types import EventType
    assert EventType.PAYMENT_PAID.value == "payment.paid"


def test_event_type_payment_refunded_exists():
    from umcp_core.events.types import EventType
    assert EventType.PAYMENT_REFUNDED.value == "payment.refunded"
