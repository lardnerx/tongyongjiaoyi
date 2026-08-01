"""规则配置服务（带内存缓存 + 变更订阅 + 默认值预加载）。

业务代码通过 RuleConfig.get(key) 读取规则，避免每次都查库；
运营后台通过 RuleConfig.set(key, value, updated_by, category) 更新规则，
set 会同步到仓储、刷新缓存、通知订阅者。
"""
from __future__ import annotations

from threading import RLock
from typing import Any, Callable

from umcp_core.shared.rules.repository import RuleRepositoryProtocol


class RuleConfig:
    """规则配置服务。"""

    def __init__(self, repo: RuleRepositoryProtocol) -> None:
        self._repo = repo
        self._cache: dict[str, Any] = {}
        self._defaults: dict[str, Any] = {}
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self._lock = RLock()

    def get(self, key: str, default: Any = None) -> Any:
        """读取规则值。优先级：缓存 > 仓储 > 默认值 > default 参数。"""
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            rule = self._repo.find_by_key(key)
            if rule is not None:
                value = rule["rule_value"]
                self._cache[key] = value
                return value
            if key in self._defaults:
                return self._defaults[key]
            return default

    def set(
        self,
        key: str,
        value: Any,
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None:
        """更新规则值：写库 + 刷新缓存 + 通知订阅者。"""
        with self._lock:
            self._repo.upsert(key, value, updated_by, category, description, reason)
            self._cache[key] = value
            for callback in self._subscribers.get(key, []):
                callback(value)

    def reload(self) -> None:
        """清空缓存，下次 get 重新查库。"""
        with self._lock:
            self._cache.clear()

    def subscribe(self, key: str, callback: Callable[[Any], None]) -> None:
        """订阅指定 key 的变更。"""
        with self._lock:
            self._subscribers.setdefault(key, []).append(callback)

    def set_defaults(self, defaults: dict[str, Any]) -> None:
        """预加载默认值。已通过 set 设置的 key 不被覆盖。"""
        with self._lock:
            for k, v in defaults.items():
                self._defaults.setdefault(k, v)
