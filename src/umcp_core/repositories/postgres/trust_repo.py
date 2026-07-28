"""PostgreSQL Trust 仓储实现（含 domain 隔离）。"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.layers.l5 import Evaluation, TrustProfile
from umcp_core.repositories.interfaces import TrustRepository
from umcp_core.repositories.postgres.converters import (
    evaluation_from_orm,
    evaluation_to_orm,
    trust_profile_from_orm,
    trust_profile_to_orm,
)
from umcp_core.repositories.postgres.models import (
    TrustEvaluationModel,
    TrustProfileModel,
)


class PostgresTrustRepository(TrustRepository):
    """PostgreSQL Trust 仓储实现，支持 domain 隔离。"""

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

    def save_profile(self, profile: TrustProfile) -> TrustProfile:
        with self._session() as session:
            model = trust_profile_to_orm(profile)
            session.merge(model)
            return profile

    def find_profile(self, user_id: str) -> TrustProfile | None:
        """返回该用户的任意一个 domain 的 profile（向后兼容）。"""
        with self._session() as session:
            stmt = select(TrustProfileModel).where(
                TrustProfileModel.user_id == user_id
            )
            model = session.execute(stmt).scalars().first()
            return trust_profile_from_orm(model) if model else None

    def find_profile_by_domain(
        self, user_id: str, domain_tag: str
    ) -> TrustProfile | None:
        """按 domain 查询信任档案。"""
        with self._session() as session:
            stmt = select(TrustProfileModel).where(
                TrustProfileModel.user_id == user_id,
                TrustProfileModel.domain_tag == domain_tag,
            )
            model = session.execute(stmt).scalar_one_or_none()
            return trust_profile_from_orm(model) if model else None

    def save_evaluation(self, evaluation: Evaluation) -> None:
        with self._session() as session:
            model = evaluation_to_orm(evaluation)
            session.merge(model)

    def find_evaluations(self, user_id: str) -> list[Evaluation]:
        with self._session() as session:
            stmt = select(TrustEvaluationModel).where(
                TrustEvaluationModel.evaluatee_id == user_id
            )
            models = session.execute(stmt).scalars().all()
            return [evaluation_from_orm(m) for m in models]
