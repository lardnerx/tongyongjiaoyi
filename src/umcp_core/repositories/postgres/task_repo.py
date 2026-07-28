"""PostgreSQL Task 仓储实现。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import Task
from umcp_core.repositories.interfaces import TaskRepository
from umcp_core.repositories.postgres.converters import (
    composite_task_from_orm,
    dependencies_from_orm,
    task_from_orm,
    task_to_orm,
)
from umcp_core.repositories.postgres.models import CompositeDependencyModel, TaskModel


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
        """upsert：存在则更新，不存在则插入。

        对于 CompositeTask，会同时设置子任务的 parent_task_id 并保存
        子任务和依赖关系（原子持久化）。
        """
        is_composite = task.task_type() == "composite"
        if is_composite:
            # 设置子任务的 parent_task_id（用于恢复时查询）
            for sub in task.subtasks:
                sub.parent_task_id = task.task_id

        with self._session() as session:
            model = task_to_orm(task)
            session.merge(model)

            if is_composite:
                # 保存子任务
                for sub in task.subtasks:
                    session.merge(task_to_orm(sub))
                # 保存依赖关系
                for sub_id, deps in task.dependencies.items():
                    for dep_id in deps:
                        session.merge(
                            CompositeDependencyModel(
                                composite_task_id=task.task_id,
                                subtask_id=sub_id,
                                depends_on_id=dep_id,
                            )
                        )
            return task

    def find_by_id(self, task_id: str) -> Task | None:
        with self._session() as session:
            stmt = select(TaskModel).where(TaskModel.task_id == task_id)
            model = session.execute(stmt).scalar_one_or_none()
            if model is None:
                return None
            return self._reconstruct_if_composite(session, model)

    def find_by_demander(self, demander_id: str) -> list[Task]:
        with self._session() as session:
            stmt = select(TaskModel).where(TaskModel.demander_id == demander_id)
            models = session.execute(stmt).scalars().all()
            return [self._reconstruct_if_composite(session, m) for m in models]

    def find_by_status(
        self, status: str, domain_tag: DomainTag | None = None
    ) -> list[Task]:
        with self._session() as session:
            stmt = select(TaskModel).where(TaskModel.status == status)
            if domain_tag is not None:
                stmt = stmt.where(TaskModel.domain_tag == domain_tag.value)
            models = session.execute(stmt).scalars().all()
            return [self._reconstruct_if_composite(session, m) for m in models]

    def update_status(self, task_id: str, new_status: str) -> None:
        with self._session() as session:
            result = session.execute(
                update(TaskModel)
                .where(TaskModel.task_id == task_id)
                .values(status=new_status, updated_at=datetime.utcnow())
            )
            if result.rowcount == 0:
                raise KeyError(f"任务不存在: {task_id}")

    def _reconstruct_if_composite(self, session: Session, model: TaskModel) -> Task:
        """如果是 CompositeTask，重建完整的子任务和依赖关系。

        子任务通过 parent_task_id 查询，依赖关系通过 composite_task_id 查询。
        """
        if model.task_type != "composite":
            return task_from_orm(model)

        # 查询子任务（按 parent_task_id）
        subtask_stmt = select(TaskModel).where(
            TaskModel.parent_task_id == model.task_id
        )
        subtask_models = session.execute(subtask_stmt).scalars().all()
        subtasks = [task_from_orm(m) for m in subtask_models]

        # 查询依赖关系
        dep_stmt = select(CompositeDependencyModel).where(
            CompositeDependencyModel.composite_task_id == model.task_id
        )
        dep_models = list(session.execute(dep_stmt).scalars().all())
        deps = dependencies_from_orm(dep_models)

        return composite_task_from_orm(model, deps, subtasks)
