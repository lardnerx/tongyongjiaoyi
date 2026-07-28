"""PostgreSQL User 仓储实现。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.core.base import User
from umcp_core.repositories.interfaces import UserRepository
from umcp_core.repositories.postgres.converters import user_from_orm, user_to_orm
from umcp_core.repositories.postgres.models import UserModel


class PostgresUserRepository(UserRepository):
    """PostgreSQL User 仓储实现。"""

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

    def save(self, user: User) -> User:
        with self._session() as session:
            model = user_to_orm(user)
            session.merge(model)
            return user

    def find_by_id(self, user_id: str) -> User | None:
        with self._session() as session:
            stmt = select(UserModel).where(UserModel.user_id == user_id)
            model = session.execute(stmt).scalar_one_or_none()
            return user_from_orm(model) if model else None

    def find_by_name(self, name: str) -> User | None:
        with self._session() as session:
            stmt = select(UserModel).where(UserModel.name == name)
            model = session.execute(stmt).scalars().first()
            return user_from_orm(model) if model else None
