"""L1 接入与身份层：认证、授权、通道加密、多端 SDK。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from umcp_core.core.base import User
from umcp_core.core.domain import Credential


class AuthProvider(ABC):
    """认证提供者接口。

    核心库提供默认实现：PhoneAuthProvider、EmailAuthProvider、WechatAuthProvider。
    行业通常无需定制此层，除非需要企业级 CA 证书认证。
    """

    @abstractmethod
    def authenticate(self, credential: Credential) -> User:
        """根据凭据进行身份认证，返回已认证用户对象。"""

    @abstractmethod
    def authorize(self, user: User, action: str) -> bool:
        """授权检查：用户是否可执行指定动作。"""

    @abstractmethod
    def revoke(self, user: User) -> None:
        """吊销用户令牌。"""


class PhoneAuthProvider(AuthProvider):
    """手机号认证提供者（默认实现）。"""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._tokens: dict[str, str] = {}

    def authenticate(self, credential: Credential) -> User:
        if credential.type != "phone":
            raise ValueError(f"PhoneAuthProvider 不支持凭据类型: {credential.type}")
        phone = credential.token
        if phone not in self._users:
            # 默认实现：自动注册新用户（生产环境应替换为正式用户库）
            from umcp_core.core.base import Demander, Supplier

            class _DefaultDemander(Demander):
                def __init__(self) -> None:
                    from umcp_core.core.base import PermissionSet

                    self._perms = PermissionSet({"publish_task", "evaluate"})

                @property
                def permissions(self):
                    return self._perms

            class _DefaultSupplier(Supplier):
                def __init__(self) -> None:
                    from umcp_core.core.base import PermissionSet

                    self._perms = PermissionSet({"register_resource", "accept_task", "evaluate"})

                @property
                def permissions(self):
                    return self._perms

            class _PhoneUser(User):
                def authenticate(self, cred: Credential) -> bool:
                    return cred.type == "phone" and cred.token == phone

            user = _PhoneUser(name=phone, metadata={"phone": phone})
            user.add_role(_DefaultDemander())
            user.add_role(_DefaultSupplier())
            self._users[phone] = user
        return self._users[phone]

    def authorize(self, user: User, action: str) -> bool:
        if user.active_role is None:
            return False
        return action in user.active_role.permissions

    def revoke(self, user: User) -> None:
        self._tokens.pop(user.user_id, None)
