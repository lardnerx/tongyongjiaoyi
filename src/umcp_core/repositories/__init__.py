"""repositories 包：数据访问抽象与内存实现。"""

from umcp_core.repositories.in_memory import (
    InMemoryDealRepository,
    InMemoryEventRepository,
    InMemoryRepositoryBundle,
    InMemoryResourceRepository,
    InMemoryTaskRepository,
    InMemoryTrustRepository,
    InMemoryUserRepository,
)
from umcp_core.repositories.interfaces import (
    DealRepository,
    EventRepository,
    ResourceRepository,
    TaskRepository,
    TrustRepository,
    UserRepository,
)

__all__ = [
    "TaskRepository",
    "ResourceRepository",
    "DealRepository",
    "UserRepository",
    "TrustRepository",
    "EventRepository",
    "InMemoryTaskRepository",
    "InMemoryResourceRepository",
    "InMemoryDealRepository",
    "InMemoryUserRepository",
    "InMemoryTrustRepository",
    "InMemoryEventRepository",
    "InMemoryRepositoryBundle",
]
