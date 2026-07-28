"""PostgreSQL Resource 仓储实现。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.repositories.interfaces import ResourceRepository
from umcp_core.repositories.postgres.converters import resource_from_orm, resource_to_orm
from umcp_core.repositories.postgres.models import ResourceModel


class PostgresResourceRepository(ResourceRepository):
    """PostgreSQL Resource 仓储实现。"""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _session(self) -> Session:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save(self, resource: Resource) -> Resource:
        with self._session() as session:
            model = resource_to_orm(resource)
            session.merge(model)
            return resource

    def find_by_id(self, resource_id: str) -> Resource | None:
        with self._session() as session:
            stmt = select(ResourceModel).where(ResourceModel.resource_id == resource_id)
            model = session.execute(stmt).scalar_one_or_none()
            return resource_from_orm(model) if model else None

    def find_by_supplier(self, supplier_id: str) -> list[Resource]:
        with self._session() as session:
            stmt = select(ResourceModel).where(ResourceModel.supplier_id == supplier_id)
            models = session.execute(stmt).scalars().all()
            return [resource_from_orm(m) for m in models]

    def find_available(self, domain_tag: DomainTag) -> list[Resource]:
        """查询指定域的可用（IDLE 状态）资源。"""
        with self._session() as session:
            stmt = (
                select(ResourceModel)
                .where(ResourceModel.domain_tag == domain_tag.value)
                .where(ResourceModel.status == ResourceStatus.IDLE)
            )
            models = session.execute(stmt).scalars().all()
            return [resource_from_orm(m) for m in models]

    def update_status(self, resource_id: str, new_status: str) -> None:
        with self._session() as session:
            result = session.execute(
                update(ResourceModel)
                .where(ResourceModel.resource_id == resource_id)
                .values(status=new_status, updated_at=datetime.utcnow())
            )
            if result.rowcount == 0:
                raise KeyError(f"资源不存在: {resource_id}")
