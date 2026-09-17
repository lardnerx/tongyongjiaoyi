"""Repository 接口定义。

核心库定义数据访问接口，不绑定具体数据库。
部署时通过依赖注入配置具体实现（如 MysqlTaskRepository）。
开发调试可使用内存实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from umcp_core.core.base import User
from umcp_core.core.deal import Deal
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource
from umcp_core.core.task import Task, TaskStatus
from umcp_core.events.bus import Event
from umcp_core.layers.l5 import Evaluation, TrustProfile


class TaskRepository(ABC):
    """任务仓储接口。"""

    @abstractmethod
    def save(self, task: Task) -> Task:
        ...

    @abstractmethod
    def find_by_id(self, task_id: str) -> Task | None:
        ...

    @abstractmethod
    def find_by_demander(self, demander_id: str) -> list[Task]:
        ...

    @abstractmethod
    def find_by_status(self, status: str, domain_tag: DomainTag | None = None) -> list[Task]:
        ...

    @abstractmethod
    def update_status(self, task_id: str, new_status: str) -> None:
        ...

    @abstractmethod
    def list_all(self) -> list[Task]:
        """返回所有任务（router 层负责过滤）。"""
        ...


class ResourceRepository(ABC):
    """资源仓储接口。"""

    @abstractmethod
    def save(self, resource: Resource) -> Resource:
        ...

    @abstractmethod
    def find_by_id(self, resource_id: str) -> Resource | None:
        ...

    @abstractmethod
    def find_by_supplier(self, supplier_id: str) -> list[Resource]:
        ...

    @abstractmethod
    def find_available(self, domain_tag: DomainTag) -> list[Resource]:
        ...

    @abstractmethod
    def update_status(self, resource_id: str, new_status: str) -> None:
        ...

    @abstractmethod
    def list_all(self) -> list[Resource]:
        """返回所有资源（router 层负责过滤）。"""
        ...


class DealRepository(ABC):
    """交易仓储接口。"""

    @abstractmethod
    def save(self, deal: Deal) -> Deal:
        ...

    @abstractmethod
    def find_by_id(self, deal_id: str) -> Deal | None:
        ...

    @abstractmethod
    def find_by_task(self, task_id: str) -> list[Deal]:
        ...

    @abstractmethod
    def find_by_supplier(self, supplier_id: str) -> list[Deal]:
        ...

    @abstractmethod
    def list_all(self) -> list[Deal]:
        """返回所有交易（router 层负责过滤）。"""
        ...


class UserRepository(ABC):
    """用户仓储接口。"""

    @abstractmethod
    def save(self, user: User) -> User:
        ...

    @abstractmethod
    def find_by_id(self, user_id: str) -> User | None:
        ...

    @abstractmethod
    def find_by_name(self, name: str) -> User | None:
        ...

    @abstractmethod
    def find_by_phone(self, phone: str) -> User | None:
        """按手机号查找用户（手机号存储在 metadata 中）。"""
        ...

    @abstractmethod
    def update_password(self, user_id: str, password_hash: str) -> None:
        """更新用户密码哈希。"""
        ...


class TrustRepository(ABC):
    """信任数据仓储接口。"""

    @abstractmethod
    def save_profile(self, profile: TrustProfile) -> TrustProfile:
        ...

    @abstractmethod
    def find_profile(self, user_id: str) -> TrustProfile | None:
        ...

    @abstractmethod
    def save_evaluation(self, evaluation: Evaluation) -> None:
        ...

    @abstractmethod
    def find_evaluations(self, user_id: str) -> list[Evaluation]:
        ...

    @abstractmethod
    def find_profile_by_domain(
        self, user_id: str, domain_tag: str
    ) -> TrustProfile | None:
        """按 domain 查询信任档案（domain 隔离）。"""
        ...


class EventRepository(ABC):
    """事件仓储接口（用于事件回放、审计）。"""

    @abstractmethod
    def append(self, event: Event) -> None:
        ...

    @abstractmethod
    def replay(self, aggregate_id: str | None = None) -> list[Event]:
        ...
