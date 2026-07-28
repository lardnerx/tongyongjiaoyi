"""PostgreSQL 仓储子包。"""

from umcp_core.repositories.postgres.bundle import PostgresRepositoryBundle
from umcp_core.repositories.postgres.task_repo import PostgresTaskRepository
from umcp_core.repositories.postgres.resource_repo import PostgresResourceRepository
from umcp_core.repositories.postgres.deal_repo import PostgresDealRepository
from umcp_core.repositories.postgres.user_repo import PostgresUserRepository
from umcp_core.repositories.postgres.trust_repo import PostgresTrustRepository
from umcp_core.repositories.postgres.event_repo import PostgresEventRepository

__all__ = [
    "PostgresRepositoryBundle",
    "PostgresTaskRepository",
    "PostgresResourceRepository",
    "PostgresDealRepository",
    "PostgresUserRepository",
    "PostgresTrustRepository",
    "PostgresEventRepository",
]
