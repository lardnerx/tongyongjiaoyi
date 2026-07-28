"""PostgreSQL Deal 仓储实现。"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.core.deal import Deal
from umcp_core.repositories.interfaces import DealRepository
from umcp_core.repositories.postgres.converters import deal_from_orm, deal_to_orm
from umcp_core.repositories.postgres.models import DealModel


class PostgresDealRepository(DealRepository):
    """PostgreSQL Deal 仓储实现。"""

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

    def save(self, deal: Deal) -> Deal:
        with self._session() as session:
            model = deal_to_orm(deal)
            session.merge(model)
            return deal

    def find_by_id(self, deal_id: str) -> Deal | None:
        with self._session() as session:
            stmt = select(DealModel).where(DealModel.deal_id == deal_id)
            model = session.execute(stmt).scalar_one_or_none()
            return deal_from_orm(model) if model else None

    def find_by_task(self, task_id: str) -> list[Deal]:
        with self._session() as session:
            stmt = select(DealModel).where(DealModel.task_id == task_id)
            models = session.execute(stmt).scalars().all()
            return [deal_from_orm(m) for m in models]

    def find_by_supplier(self, supplier_id: str) -> list[Deal]:
        with self._session() as session:
            stmt = select(DealModel).where(DealModel.supplier_id == supplier_id)
            models = session.execute(stmt).scalars().all()
            return [deal_from_orm(m) for m in models]
