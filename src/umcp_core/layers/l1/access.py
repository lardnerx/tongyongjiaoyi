"""L1 接入与身份层：认证、授权、通道加密、多端 SDK。"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from umcp_core.core.base import User
from umcp_core.core.domain import Credential


def hash_password(password: str) -> str:
    """对密码进行 PBKDF2-HMAC-SHA256 哈希，返回 salt$hash 格式。"""
    salt = os.urandom(16).hex()
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${pwd_hash}"


def verify_password(password: str, stored: str) -> bool:
    """验证密码是否与存储的哈希匹配。"""
    try:
        salt, pwd_hash = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
        return check == pwd_hash
    except (ValueError, AttributeError):
        return False


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

    @abstractmethod
    def register(self, credential: Credential, name: str) -> User:
        """注册新用户。返回已创建的用户对象。"""


class PhoneAuthProvider(AuthProvider):
    """手机号认证提供者（默认实现）。

    支持两种用户来源：
    1. 通过 register() 注册的用户（持久化到 UserRepository）
    2. 自动创建的用户（兼容旧逻辑，通过 authenticate() 首次登录时自动创建）

    Args:
        user_repo: 可选的 UserRepository 实例。提供后注册用户会持久化，
                   authenticate 也会优先查询仓储。
    """

    def __init__(self, user_repo: Any = None, cache_ttl: int = 60) -> None:
        self._users: dict[str, User] = {}
        self._tokens: dict[str, str] = {}
        self._user_repo = user_repo
        self._cache_ttl = cache_ttl  # 缓存有效期（秒），到期后自动从仓储刷新
        self._cache_timestamps: dict[str, float] = {}  # 各用户缓存写入时间戳
        # 并发控制
        self._cache_lock = threading.Lock()  # 保护 _users / _cache_timestamps 的并发读写
        self._refresh_locks: dict[str, threading.Lock] = {}  # 每个 key 的刷新互斥锁，防止缓存击穿
        self._refresh_locks_lock = threading.Lock()  # 保护 _refresh_locks 的并发访问

    def _build_user(self, phone: str, name: str = "", password: str = "") -> User:
        """创建带有 Demander + Supplier 角色的用户。"""
        from umcp_core.core.base import Demander, PermissionSet, Supplier

        class _DefaultDemander(Demander):
            def __init__(self) -> None:
                self._perms = PermissionSet({"publish_task", "evaluate"})

            @property
            def permissions(self):
                return self._perms

        class _DefaultSupplier(Supplier):
            def __init__(self) -> None:
                self._perms = PermissionSet({"register_resource", "accept_task", "evaluate"})

            @property
            def permissions(self):
                return self._perms

        class _PhoneUser(User):
            def authenticate(self, cred: Credential) -> bool:
                return cred.type == "phone" and cred.token == phone

        display_name = name or phone
        metadata: dict[str, Any] = {"phone": phone}
        if password:
            metadata["password_hash"] = hash_password(password)
        user = _PhoneUser(name=display_name, metadata=metadata)
        user.add_role(_DefaultDemander())
        user.add_role(_DefaultSupplier())
        return user

    def _get_refresh_lock(self, key: str) -> threading.Lock:
        """获取指定 key 的刷新互斥锁。

        同一时刻只有一个线程可以刷新该 key 的缓存，防止缓存击穿（thundering herd）。
        锁对象在 _refresh_locks 中按需创建，不会无限增长（活跃用户数有限）。
        """
        with self._refresh_locks_lock:
            if key not in self._refresh_locks:
                self._refresh_locks[key] = threading.Lock()
            return self._refresh_locks[key]

    def _is_cache_valid(self, phone: str) -> bool:
        """检查缓存是否仍在有效期内（线程安全，自包含锁保护）。"""
        with self._cache_lock:
            if phone not in self._cache_timestamps:
                return False
            elapsed = time.time() - self._cache_timestamps[phone]
            return elapsed < self._cache_ttl

    def _update_cache(self, phone: str, user: User) -> None:
        """写入缓存并记录时间戳（线程安全）。"""
        with self._cache_lock:
            self._users[phone] = user
            self._cache_timestamps[phone] = time.time()

    def _read_cache(self, phone: str) -> User | None:
        """从缓存读取用户（线程安全）。"""
        with self._cache_lock:
            return self._users.get(phone)

    def authenticate(self, credential: Credential) -> User:
        if credential.type != "phone":
            raise ValueError(f"PhoneAuthProvider 不支持凭据类型: {credential.type}")
        phone = credential.token
        password = credential.payload.get("password", "")

        # 1. 快速路径：缓存命中且未过期 → 直接返回（避免重复查仓储）
        cached = self._read_cache(phone)
        if cached is not None and self._is_cache_valid(phone):
            self._verify_user_password(cached, password)
            return cached

        # 2. 双重检查锁：获取 per-key 刷新锁，防止缓存击穿
        #    同一时刻只有第一个线程进入仓储查询，其他线程等待锁释放后直接读缓存
        refresh_lock = self._get_refresh_lock(phone)
        with refresh_lock:
            # 2a. 再次检查缓存（可能在等待锁期间已被其他线程刷新）
            cached = self._read_cache(phone)
            if cached is not None and self._is_cache_valid(phone):
                self._verify_user_password(cached, password)
                return cached

            # 2b. 缓存过期或未命中 → 从仓储获取最新数据
            if self._user_repo:
                found = self._user_repo.find_by_phone(phone)
                if found is not None:
                    self._verify_user_password(found, password)
                    self._update_cache(phone, found)
                    return found

            # 2c. 仓储不可用 → 回退到缓存（即使过期也比完全查不到好）
            cached = self._read_cache(phone)
            if cached is not None:
                self._verify_user_password(cached, password)
                return cached

            # 2d. 兜底：自动注册新用户（兼容旧逻辑）
            user = self._build_user(phone)
            self._update_cache(phone, user)
            if self._user_repo:
                self._user_repo.save(user)
            return user

    def _verify_user_password(self, user: User, password: str) -> None:
        """验证用户密码，如果用户设置了密码但未提供或错误则抛出异常。"""
        pwd_hash = user.metadata.get("password_hash", "")
        if pwd_hash:
            if not password:
                raise ValueError("需要密码")
            if not verify_password(password, pwd_hash):
                raise ValueError("密码错误")

    def authorize(self, user: User, action: str) -> bool:
        if user.active_role is None:
            return False
        return action in user.active_role.permissions

    def revoke(self, user: User) -> None:
        self._tokens.pop(user.user_id, None)

    def register(self, credential: Credential, name: str) -> User:
        """注册新用户。

        Args:
            credential: 凭据（type="phone", token=手机号, payload 可含 password）
            name: 用户昵称/姓名

        Returns:
            创建好的 User 对象

        Raises:
            ValueError: 手机号已注册
        """
        if credential.type != "phone":
            raise ValueError(f"PhoneAuthProvider 不支持凭据类型: {credential.type}")
        phone = credential.token
        password = credential.payload.get("password", "")
        # 检查是否已注册
        if phone in self._users:
            raise ValueError(f"手机号 {phone} 已注册")
        if self._user_repo and self._user_repo.find_by_phone(phone) is not None:
            raise ValueError(f"手机号 {phone} 已注册")
        user = self._build_user(phone, name=name, password=password)
        self._update_cache(phone, user)
        if self._user_repo:
            self._user_repo.save(user)
        return user

    def reset_password(self, phone: str, new_password: str) -> User:
        """重置用户密码（无需旧密码，用于忘记密码场景）。

        Args:
            phone: 手机号
            new_password: 新密码

        Returns:
            更新后的 User 对象

        Raises:
            ValueError: 用户不存在
        """
        user: User | None = None
        # 从缓存查找
        if phone in self._users:
            user = self._users[phone]
        # 从仓储查找
        if user is None and self._user_repo:
            user = self._user_repo.find_by_phone(phone)
        if user is None:
            raise ValueError(f"手机号 {phone} 未注册")

        # 更新为新密码哈希
        user.metadata["password_hash"] = hash_password(new_password)
        if self._user_repo:
            self._user_repo.save(user)
        # 更新缓存
        self._update_cache(phone, user)
        return user

    def change_password(self, user_id: str, old_password: str, new_password: str) -> User:
        """修改用户密码。

        Args:
            user_id: 用户 ID
            old_password: 旧密码
            new_password: 新密码

        Returns:
            更新后的 User 对象

        Raises:
            ValueError: 用户不存在或旧密码错误
        """
        user: User | None = None
        # 从缓存查找
        for u in self._users.values():
            if u.user_id == user_id:
                user = u
                break
        # 从仓储查找
        if user is None and self._user_repo:
            user = self._user_repo.find_by_id(user_id)
        if user is None:
            raise ValueError("用户不存在")

        # 验证旧密码
        existing_hash = user.metadata.get("password_hash", "")
        if existing_hash:
            if not old_password:
                raise ValueError("需要旧密码")
            if not verify_password(old_password, existing_hash):
                raise ValueError("旧密码错误")
        # 更新为新密码哈希
        user.metadata["password_hash"] = hash_password(new_password)
        if self._user_repo:
            self._user_repo.save(user)
        # 更新缓存
        phone = user.metadata.get("phone", "")
        if phone:
            self._update_cache(phone, user)
        return user