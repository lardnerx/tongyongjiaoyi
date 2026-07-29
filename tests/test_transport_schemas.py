"""transport 错误体系和 schemas 测试。"""

from __future__ import annotations

import pytest

from umcp_core.transport.errors import (
    ApiError,
    InvalidCredentialError,
    TokenExpiredError,
    PermissionDeniedError,
    NotFoundError,
    IllegalStateError,
    ValidationError,
    MatchFailedError,
    PaymentFailedError,
)
from umcp_core.transport.schemas import (
    Envelope,
    PaginatedData,
    ok,
    paginated,
)


class TestApiError:
    def test_base_api_error_carries_code_message_status_details(self):
        err = ApiError(code=9999, message="x", status=418, details={"k": "v"})
        assert err.code == 9999
        assert err.message == "x"
        assert err.status == 418
        assert err.details == {"k": "v"}

    def test_invalid_credential_error(self):
        err = InvalidCredentialError()
        assert err.code == 1001
        assert err.status == 401

    def test_token_expired_error(self):
        err = TokenExpiredError()
        assert err.code == 1002
        assert err.status == 401

    def test_permission_denied_error(self):
        err = PermissionDeniedError()
        assert err.code == 1003
        assert err.status == 403

    def test_not_found_error(self):
        err = NotFoundError()
        assert err.code == 2001
        assert err.status == 404

    def test_illegal_state_error(self):
        err = IllegalStateError()
        assert err.code == 2002
        assert err.status == 409

    def test_validation_error(self):
        err = ValidationError()
        assert err.code == 2003
        assert err.status == 422

    def test_match_failed_error(self):
        err = MatchFailedError()
        assert err.code == 3001
        assert err.status == 422

    def test_payment_failed_error(self):
        err = PaymentFailedError()
        assert err.code == 3002
        assert err.status == 422


class TestEnvelope:
    def test_ok_envelope(self):
        env = ok({"task_id": "t1"})
        assert env.code == 0
        assert env.data == {"task_id": "t1"}
        assert env.message == "ok"

    def test_ok_with_message(self):
        env = ok(data=None, message="created")
        assert env.code == 0
        assert env.data is None
        assert env.message == "created"

    def test_paginated(self):
        env = paginated(items=[1, 2, 3], total=100, page=1, size=20)
        assert env.code == 0
        assert isinstance(env.data, PaginatedData)
        assert env.data.items == [1, 2, 3]
        assert env.data.total == 100
        assert env.data.page == 1
        assert env.data.size == 20
