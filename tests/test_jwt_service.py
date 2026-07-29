"""JwtService 单元测试。"""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest

from umcp_core.core.base import Demander, PermissionSet, Role, Supplier, User
from umcp_core.core.domain import Credential
from umcp_core.transport.auth import JwtService


class _TestDemander(Demander):
    def __init__(self) -> None:
        self._perms = PermissionSet({"publish_task", "evaluate"})

    @property
    def permissions(self) -> PermissionSet:
        return self._perms


class _TestSupplier(Supplier):
    def __init__(self) -> None:
        self._perms = PermissionSet({"register_resource", "accept_task", "evaluate"})

    @property
    def permissions(self) -> PermissionSet:
        return self._perms


class _TestUser(User):
    def __init__(self, user_id: str = "u_test", name: str = "13800000000") -> None:
        super().__init__(user_id=user_id, name=name)
        self.add_role(_TestDemander())
        self.switch_role("demander")

    def authenticate(self, cred: Credential) -> bool:
        return True


def _make_user() -> _TestUser:
    user = _TestUser()
    user.add_role(_TestSupplier())
    return user


class TestJwtIssue:
    def test_issue_returns_access_and_refresh(self):
        svc = JwtService(secret="test-secret")
        user = _make_user()
        tokens = svc.issue(user)
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == 3600

    def test_access_token_contains_required_claims(self):
        svc = JwtService(secret="test-secret")
        user = _make_user()
        tokens = svc.issue(user)
        payload = pyjwt.decode(
            tokens["access_token"], "test-secret", algorithms=["HS256"]
        )
        assert payload["sub"] == "u_test"
        assert payload["name"] == "13800000000"
        assert "demander" in payload["roles"]
        assert "supplier" in payload["roles"]
        assert payload["active_role"] == "demander"
        assert "iat" in payload
        assert "exp" in payload
        assert "jti" in payload


class TestJwtDecode:
    def test_decode_valid_token(self):
        svc = JwtService(secret="test-secret")
        user = _make_user()
        tokens = svc.issue(user)
        payload = svc.decode(tokens["access_token"])
        assert payload["sub"] == "u_test"

    def test_decode_expired_token_raises(self):
        svc = JwtService(secret="test-secret", access_ttl=1)
        user = _make_user()
        tokens = svc.issue(user)
        time.sleep(2)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            svc.decode(tokens["access_token"])

    def test_decode_wrong_secret_raises(self):
        svc = JwtService(secret="secret-a")
        user = _make_user()
        tokens = svc.issue(user)
        svc_b = JwtService(secret="secret-b")
        with pytest.raises(pyjwt.InvalidSignatureError):
            svc_b.decode(tokens["access_token"])

    def test_decode_malformed_token_raises(self):
        svc = JwtService(secret="test-secret")
        with pytest.raises(pyjwt.DecodeError):
            svc.decode("not.a.valid.token")


class TestJwtRevoke:
    def test_revoke_adds_to_blacklist(self):
        svc = JwtService(secret="test-secret")
        user = _make_user()
        tokens = svc.issue(user)
        payload = svc.decode(tokens["access_token"])
        assert svc.is_revoked(payload["jti"]) is False
        svc.revoke(payload["jti"])
        assert svc.is_revoked(payload["jti"]) is True

    def test_revoke_unknown_jti_is_noop(self):
        svc = JwtService(secret="test-secret")
        svc.revoke("unknown-jti")
        assert svc.is_revoked("unknown-jti") is True


class TestJwtRefresh:
    def test_refresh_token_has_longer_exp(self):
        svc = JwtService(secret="test-secret", access_ttl=3600, refresh_ttl=604800)
        user = _make_user()
        tokens = svc.issue(user)
        access_payload = svc.decode(tokens["access_token"])
        refresh_payload = svc.decode(tokens["refresh_token"])
        assert refresh_payload["exp"] - refresh_payload["iat"] == 604800
        assert access_payload["exp"] - access_payload["iat"] == 3600
