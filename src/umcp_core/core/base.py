"""核心抽象：User、Role、Demander、Supplier。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from umcp_core.core.domain import Credential


class PermissionSet:
    """权限集合。"""

    def __init__(self, permissions: set[str] | None = None) -> None:
        self._permissions: set[str] = set(permissions) if permissions else set()

    def grant(self, permission: str) -> None:
        self._permissions.add(permission)

    def revoke(self, permission: str) -> None:
        self._permissions.discard(permission)

    def has(self, permission: str) -> bool:
        return permission in self._permissions

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return self.has(item)
        return False

    def __iter__(self):
        return iter(self._permissions)


class Role(ABC):
    """角色根抽象。一个 User 可关联多个 Role，运行时切换 activeRole。"""

    @property
    @abstractmethod
    def role_type(self) -> str:
        """返回角色类型标识，如 'demander' 或 'supplier'。"""

    @property
    @abstractmethod
    def permissions(self) -> PermissionSet:
        """该角色具备的权限集合。"""


class Demander(Role, ABC):
    """需求方角色接口。"""

    @property
    def role_type(self) -> str:
        return "demander"


class Supplier(Role, ABC):
    """供给方角色接口。"""

    @property
    def role_type(self) -> str:
        return "supplier"


class User(ABC):
    """平台参与者根抽象。

    一个用户可同时具备需求方与供给方身份，通过 active_role 切换当前活动角色。
    """

    def __init__(
        self,
        user_id: str | None = None,
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.user_id: str = user_id or f"u_{uuid.uuid4().hex[:12]}"
        self.name: str = name
        self.roles: dict[str, Role] = {}
        self.active_role: Role | None = None
        self.metadata: dict[str, Any] = metadata or {}

    @abstractmethod
    def authenticate(self, credential: Credential) -> bool:
        """根据凭据进行身份认证。"""

    def add_role(self, role: Role) -> None:
        """为用户添加一个角色。"""
        self.roles[role.role_type] = role
        if self.active_role is None:
            self.active_role = role

    def switch_role(self, role_type: str) -> None:
        """切换当前活动角色。"""
        if role_type not in self.roles:
            raise ValueError(f"用户未关联角色: {role_type}")
        self.active_role = self.roles[role_type]

    def is_demander(self) -> bool:
        return isinstance(self.active_role, Demander)

    def is_supplier(self) -> bool:
        return isinstance(self.active_role, Supplier)

    def __repr__(self) -> str:
        role = self.active_role.role_type if self.active_role else "none"
        return f"<User id={self.user_id} name={self.name!r} role={role}>"
