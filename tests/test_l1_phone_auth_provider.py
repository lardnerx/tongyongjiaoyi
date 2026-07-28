"""测试 L1 接入与身份层：PhoneAuthProvider。

覆盖 src/umcp_core/layers/l1/access.py。

注意：实际 API 为
- authenticate(credential: Credential) -> User
- authorize(user: User, action: str) -> bool
- revoke(user: User) -> None
"""

from __future__ import annotations

import pytest

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.layers.l1 import AuthProvider, PhoneAuthProvider


# ----------------------------------------------------------------------
# PhoneAuthProvider
# ----------------------------------------------------------------------


class TestPhoneAuthProvider:
    def test_is_auth_provider_subclass(self):
        provider = PhoneAuthProvider()
        assert isinstance(provider, AuthProvider)

    def test_authenticate_new_user_auto_registers(self):
        """新手机号首次认证应自动注册并返回 User 对象。"""
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        assert isinstance(user, User)
        # phone 字段保存在 metadata 中
        assert user.metadata.get("phone") == "13800000001"
        # name 也默认为 phone
        assert user.name == "13800000001"

    def test_authenticate_new_user_has_demander_and_supplier_roles(self):
        """自动注册的用户应同时具备 demander 与 supplier 角色。"""
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        assert "demander" in user.roles
        assert "supplier" in user.roles
        # 首个添加的角色应被自动激活
        assert user.active_role is not None
        assert user.active_role.role_type == "demander"

    def test_authenticate_new_user_demander_permissions(self):
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        user.switch_role("demander")
        perms = user.active_role.permissions
        assert "publish_task" in perms
        assert "evaluate" in perms

    def test_authenticate_new_user_supplier_permissions(self):
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        user.switch_role("supplier")
        perms = user.active_role.permissions
        assert "register_resource" in perms
        assert "accept_task" in perms
        assert "evaluate" in perms

    def test_authenticate_existing_user_returns_same_instance(self):
        """同一手机号再次认证应返回同一 User 实例（幂等）。"""
        provider = PhoneAuthProvider()
        user1 = provider.authenticate(Credential.phone("13800000001"))
        user2 = provider.authenticate(Credential.phone("13800000001"))
        assert user1 is user2

    def test_authenticate_different_phones_return_different_users(self):
        provider = PhoneAuthProvider()
        user1 = provider.authenticate(Credential.phone("13800000001"))
        user2 = provider.authenticate(Credential.phone("13800000002"))
        assert user1 is not user2
        assert user1.user_id != user2.user_id

    def test_authenticate_rejects_non_phone_credential(self):
        """非 phone 类型的凭据应抛 ValueError。"""
        provider = PhoneAuthProvider()
        with pytest.raises(ValueError, match="PhoneAuthProvider 不支持凭据类型"):
            provider.authenticate(Credential(type="email", token="a@b.com"))

    def test_authenticate_user_can_authenticate_with_matching_phone(self):
        """_PhoneUser.authenticate 应校验 phone 凭据。"""
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        # 正确手机号 + phone 类型 → True
        assert user.authenticate(Credential.phone("13800000001")) is True
        # 错误手机号 → False
        assert user.authenticate(Credential.phone("13900000000")) is False
        # 非 phone 类型 → False
        assert user.authenticate(Credential(type="email", token="x@y.com")) is False


class TestPhoneAuthProviderAuthorize:
    def test_authorize_allows_permitted_action(self):
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        # 默认 active_role 为 demander，含 publish_task
        assert provider.authorize(user, "publish_task") is True

    def test_authorize_denies_unpermitted_action(self):
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        # demander 角色不具备 register_resource
        assert provider.authorize(user, "register_resource") is False

    def test_authorize_after_role_switch(self):
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        # 切换到 supplier 后具备 register_resource
        user.switch_role("supplier")
        assert provider.authorize(user, "register_resource") is True
        assert provider.authorize(user, "publish_task") is False

    def test_authorize_user_without_active_role_returns_false(self):
        """active_role 为 None 时应拒绝。"""
        provider = PhoneAuthProvider()

        class _BareUser(User):
            def authenticate(self, credential: Credential) -> bool:
                return True

        bare = _BareUser(name="anon")
        # 未添加任何角色 → active_role is None
        assert provider.authorize(bare, "anything") is False


class TestPhoneAuthProviderRevoke:
    def test_revoke_removes_token(self):
        """revoke 应清除 _tokens 中的令牌记录。"""
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential.phone("13800000001"))
        # 直接注入一个 token 以验证 revoke 行为
        provider._tokens[user.user_id] = "some_token"
        assert user.user_id in provider._tokens
        provider.revoke(user)
        assert user.user_id not in provider._tokens

    def test_revoke_when_no_token_is_noop(self):
        """revoke 不存在的令牌应静默成功。"""
        provider = PhoneAuthProvider()

        class _BareUser(User):
            def authenticate(self, credential: Credential) -> bool:
                return True

        user = _BareUser(name="anon")
        # 不应抛错
        provider.revoke(user)
        assert user.user_id not in provider._tokens
