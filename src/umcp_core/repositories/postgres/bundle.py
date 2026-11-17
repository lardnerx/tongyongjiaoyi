"""PostgreSQL 仓储套件。"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.repositories.postgres.deal_repo import PostgresDealRepository
from umcp_core.repositories.postgres.event_repo import PostgresEventRepository
from umcp_core.repositories.postgres.models import Base
from umcp_core.repositories.postgres.resource_repo import PostgresResourceRepository
from umcp_core.repositories.postgres.task_repo import PostgresTaskRepository
from umcp_core.repositories.postgres.trust_repo import PostgresTrustRepository
from umcp_core.repositories.postgres.user_repo import PostgresUserRepository
from umcp_core.shared.rules.models import (  # noqa: F401  导入以注册建表元数据
    BusinessRuleHistoryModel,
    BusinessRuleModel,
)
from umcp_core.shared.rules.repository import PostgresRuleRepository
from umcp_core.shared.payment.repository import PostgresPaymentRepository


class PostgresRepositoryBundle:
    """PostgreSQL 仓储套件，提供 6 个仓储 + 事件仓储 + 支付仓储。

    用法：
        bundle = PostgresRepositoryBundle("postgresql://...")
        server.use_postgres_repositories("postgresql://...")
    """

    def __init__(
        self,
        dsn: str,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_recycle: int = 3600,
        pool_timeout: int = 30,
    ) -> None:
        self.engine = create_engine(
            dsn,
            echo=echo,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
        )
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

        # 仓储实例（逐步填充，本任务只填充 task_repo）
        self.task_repo = PostgresTaskRepository(self.SessionFactory)
        self.resource_repo = PostgresResourceRepository(self.SessionFactory)
        self.deal_repo = PostgresDealRepository(self.SessionFactory)
        self.user_repo = PostgresUserRepository(self.SessionFactory)
        self.trust_repo = PostgresTrustRepository(self.SessionFactory)
        self.event_repo = PostgresEventRepository(self.SessionFactory)
        self.rule_repo = PostgresRuleRepository(self.SessionFactory)
        self.payment_repo = PostgresPaymentRepository(self.SessionFactory)

    @contextmanager
    def transaction(self) -> Session:
        """跨仓储的事务上下文。"""
        session = self.SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
