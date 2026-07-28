"""PostgreSQL 仓储套件。"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.repositories.postgres.models import Base
from umcp_core.repositories.postgres.task_repo import PostgresTaskRepository


class PostgresRepositoryBundle:
    """PostgreSQL 仓储套件，提供 6 个仓储 + 事件仓储。

    用法：
        bundle = PostgresRepositoryBundle("postgresql://...")
        server.use_postgres_repositories("postgresql://...")
    """

    def __init__(self, dsn: str, echo: bool = False) -> None:
        self.engine = create_engine(
            dsn,
            echo=echo,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_timeout=30,
        )
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

        # 仓储实例（逐步填充，本任务只填充 task_repo）
        self.task_repo = PostgresTaskRepository(self.SessionFactory)
        self.resource_repo = None  # 任务 3 填充
        self.deal_repo = None      # 任务 4 填充
        self.user_repo = None      # 任务 4 填充
        self.trust_repo = None     # 任务 5 填充
        self.event_repo = None     # 任务 6 填充

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
