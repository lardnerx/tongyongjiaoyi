"""PostgreSQL Task 仓储实现。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import Task
from umcp_core.repositories.interfaces import TaskRepository
from umcp_core.repositories.postgres.converters import task_from_orm, task_to_orm
from umcp_core.repositories.postgres.models import TaskModel


class PostgresTaskRepository(TaskRepository):
    """PostgreSQL 实现，依赖注入 SessionFactory。"""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _session(self) -> Session:
        """提供事务上下文，自动 commit/rollback。"""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save(self, task: Task) -> Task:
        """upsert：存在则更新，不存在则插入。"""
        with self._session() as session:
            model = task_to_orm(task)
            session.merge(model)
            return task

    def find_by_id(self, task_id: str) -> Task | None:
        with self._session() as session:
            stmt = select(TaskModel).where(TaskModel.task_id == task_id)
            model = session.execute(stmt).scalar_one_or_none()
            return task_from_orm(model) if model else None

    def find_by_demander(self, demander_id: str) -> list[Task]:
        with self._session() as session:
            stmt = select(TaskModel).where(TaskModel.demander_id == demander_id)
            models = session.execute(stmt).scalars().all()
            return [task_from_orm(m) for m in models]

    def find_by_status(
        self, status: str, domain_tag: DomainTag | None = None
    ) -> list[Task]:
        with self._session() as session:
            stmt = select(TaskModel).where(TaskModel.status == status)
            if domain_tag is not None:
                stmt = stmt.where(TaskModel.domain_tag == domain_tag.value)
            models = session.execute(stmt).scalars().all()
            return [task_from_orm(m) for m in models]

    def update_status(self, task_id: str, new_status: str) -> None:
        with self._session() as session:
            result = session.execute(
                update(TaskModel)
                .where(TaskModel.task_id == task_id)
                .values(status=new_status, updated_at=datetime.utcnow())
            )
            if result.rowcount == 0:
                raise KeyError(f"任务不存在: {task_id}")
