"""JWT 签发、校验、吊销服务。"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt as pyjwt

from umcp_core.core.base import Demander, PermissionSet, Role, Supplier, User
from umcp_core.core.domain import Credential


class JwtService:
    """JWT 令牌服务：签发 access + refresh，校验，黑名单吊销。

    access token 默认 1h，refresh token 默认 7d。黑名单为内存 set[jti]，
    单进程部署足够，多进程需换 Redis（阶段五C）。
    """

    def __init__(
        self,
        secret: str,
        access_ttl: int = 3600,
        refresh_ttl: int = 604800,
    ) -> None:
        self._secret = secret
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._blacklist: set[str] = set()
        self._lock = threading.RLock()

    def issue(self, user: User) -> dict[str, Any]:
        """签发 token 对。返回 {access_token, refresh_token, token_type, expires_in}。"""
        now = datetime.now(timezone.utc)
        base_claims = {
            "sub": user.user_id,
            "name": user.name,
            "roles": list(user.roles.keys()),
            "active_role": user.active_role.role_type if user.active_role else None,
        }
        access_payload = {
            **base_claims,
            "iat": now,
            "exp": now + timedelta(seconds=self._access_ttl),
            "jti": uuid.uuid4().hex,
            "type": "access",
        }
        refresh_payload = {
            **base_claims,
            "iat": now,
            "exp": now + timedelta(seconds=self._refresh_ttl),
            "jti": uuid.uuid4().hex,
            "type": "refresh",
        }
        access_token = pyjwt.encode(access_payload, self._secret, algorithm="HS256")
        refresh_token = pyjwt.encode(refresh_payload, self._secret, algorithm="HS256")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": self._access_ttl,
        }

    def decode(self, token: str) -> dict[str, Any]:
        """解码并验证 JWT。失败抛 pyjwt.InvalidTokenError 子类。"""
        return pyjwt.decode(token, self._secret, algorithms=["HS256"])

    def revoke(self, jti: str) -> None:
        """加入黑名单。"""
        with self._lock:
            self._blacklist.add(jti)

    def is_revoked(self, jti: str) -> bool:
        """检查是否在黑名单。"""
        with self._lock:
            return jti in self._blacklist


def user_from_claims(payload: dict[str, Any]) -> User:
    """从 JWT claims 重建轻量 User 对象（不查库）。

    重建的 User 只用于路由层的角色守卫和身份标识，不参与 authenticate。
    """
    user_id = payload.get("sub", "")
    name = payload.get("name", "")
    roles_claim: list[str] = payload.get("roles", [])
    active_role_type = payload.get("active_role")

    user = _ClaimsUser(user_id=user_id, name=name)
    for role_type in roles_claim:
        if role_type == "demander":
            user.add_role(_ClaimsDemander())
        elif role_type == "supplier":
            user.add_role(_ClaimsSupplier())
    if active_role_type and active_role_type in user.roles:
        user.switch_role(active_role_type)
    return user


class _ClaimsDemander(Demander):
    def __init__(self) -> None:
        self._perms = PermissionSet({"publish_task", "evaluate"})

    @property
    def permissions(self) -> PermissionSet:
        return self._perms


class _ClaimsSupplier(Supplier):
    def __init__(self) -> None:
        self._perms = PermissionSet({"register_resource", "accept_task", "evaluate"})

    @property
    def permissions(self) -> PermissionSet:
        return self._perms


class _ClaimsUser(User):
    """从 JWT claims 重建的轻量 User。authenticate 永远返回 True（已通过 JWT 校验）。"""

    def authenticate(self, cred: Credential) -> bool:
        return True
