"""内存版 Repository 实现。

开发调试可使用内存实现，开箱即跑。
生产环境应替换为 MySQL/PostgreSQL/MongoDB 等具体实现。
"""

from __future__ import annotations

import threading
from typing import Any

from umcp_core.core.base import User
from umcp_core.core.deal import Deal
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import Task, TaskStatus
from umcp_core.events.bus import Event
from umcp_core.layers.l5 import Evaluation, TrustProfile
from umcp_core.repositories.interfaces import (
    DealRepository,
    EventRepository,
    ResourceRepository,
    TaskRepository,
    TrustRepository,
    UserRepository,
)


class InMemoryTaskRepository(TaskRepository):
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    def save(self, task: Task) -> Task:
        with self._lock:
            self._tasks[task.task_id] = task
            return task

    def find_by_id(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def find_by_demander(self, demander_id: str) -> list[Task]:
        return [t for t in self._tasks.values() if t.demander_id == demander_id]

    def find_by_status(
        self, status: str, domain_tag: DomainTag | None = None
    ) -> list[Task]:
        result = [t for t in self._tasks.values() if t.status == status]
        if domain_tag is not None:
            result = [t for t in result if t.domain_tag == domain_tag]
        return result

    def update_status(self, task_id: str, new_status: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"任务不存在: {task_id}")
            task.status = new_status


class InMemoryResourceRepository(ResourceRepository):
    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._lock = threading.RLock()

    def save(self, resource: Resource) -> Resource:
        with self._lock:
            self._resources[resource.resource_id] = resource
            return resource

    def find_by_id(self, resource_id: str) -> Resource | None:
        return self._resources.get(resource_id)

    def find_by_supplier(self, supplier_id: str) -> list[Resource]:
        return [r for r in self._resources.values() if r.supplier_id == supplier_id]

    def find_available(self, domain_tag: DomainTag) -> list[Resource]:
        return [
            r
            for r in self._resources.values()
            if r.domain_tag == domain_tag and r.is_available()
        ]

    def update_status(self, resource_id: str, new_status: str) -> None:
        with self._lock:
            resource = self._resources.get(resource_id)
            if resource is None:
                raise KeyError(f"资源不存在: {resource_id}")
            resource.status = new_status


class InMemoryDealRepository(DealRepository):
    def __init__(self) -> None:
        self._deals: dict[str, Deal] = {}
        self._lock = threading.RLock()

    def save(self, deal: Deal) -> Deal:
        with self._lock:
            self._deals[deal.deal_id] = deal
            return deal

    def find_by_id(self, deal_id: str) -> Deal | None:
        return self._deals.get(deal_id)

    def find_by_task(self, task_id: str) -> list[Deal]:
        return [d for d in self._deals.values() if d.task_id == task_id]

    def find_by_supplier(self, supplier_id: str) -> list[Deal]:
        return [d for d in self._deals.values() if d.supplier_id == supplier_id]


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._by_name: dict[str, User] = {}
        self._lock = threading.RLock()

    def save(self, user: User) -> User:
        with self._lock:
            self._users[user.user_id] = user
            if user.name:
                self._by_name[user.name] = user
            return user

    def find_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def find_by_name(self, name: str) -> User | None:
        return self._by_name.get(name)


class InMemoryTrustRepository(TrustRepository):
    def __init__(self) -> None:
        self._profiles: dict[str, TrustProfile] = {}
        self._evaluations: dict[str, list[Evaluation]] = {}
        self._lock = threading.RLock()

    def save_profile(self, profile: TrustProfile) -> TrustProfile:
        with self._lock:
            self._profiles[profile.user_id] = profile
            return profile

    def find_profile(self, user_id: str) -> TrustProfile | None:
        return self._profiles.get(user_id)

    def save_evaluation(self, evaluation: Evaluation) -> None:
        with self._lock:
            self._evaluations.setdefault(evaluation.evaluatee_id, []).append(evaluation)

    def find_evaluations(self, user_id: str) -> list[Evaluation]:
        return list(self._evaluations.get(user_id, []))


class InMemoryEventRepository(EventRepository):
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._lock = threading.RLock()

    def append(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)

    def replay(self, aggregate_id: str | None = None) -> list[Event]:
        with self._lock:
            if aggregate_id is None:
                return list(self._events)
            return [
                e
                for e in self._events
                if e.payload.get("task_id") == aggregate_id
                or e.payload.get("deal_id") == aggregate_id
                or e.payload.get("user_id") == aggregate_id
            ]


class InMemoryRepositoryBundle:
    """内存仓储包：一次性注入所有仓储。"""

    def __init__(self) -> None:
        self.task_repo: InMemoryTaskRepository = InMemoryTaskRepository()
        self.resource_repo: InMemoryResourceRepository = InMemoryResourceRepository()
        self.deal_repo: InMemoryDealRepository = InMemoryDealRepository()
        self.user_repo: InMemoryUserRepository = InMemoryUserRepository()
        self.trust_repo: InMemoryTrustRepository = InMemoryTrustRepository()
        self.event_repo: InMemoryEventRepository = InMemoryEventRepository()
