"""PostgreSQL Event 仓储实现（事件日志，支持回放）。"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.events.bus import Event
from umcp_core.repositories.interfaces import EventRepository
from umcp_core.repositories.postgres.converters import event_from_orm, event_to_orm
from umcp_core.repositories.postgres.models import EventModel


class PostgresEventRepository(EventRepository):
    """PostgreSQL Event 仓储实现。

    用于事件持久化与审计回放。append 失败不阻塞主流程（日志告警）。
    """

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

    def append(self, event: Event) -> None:
        """追加事件到日志。事件持久化失败时仅告警，不抛异常。"""
        try:
            with self._session() as session:
                model = event_to_orm(event)
                session.add(model)
        except Exception as e:
            import sys
            print(f"[PostgresEventRepository] 事件持久化失败: {e}", file=sys.stderr)

    def replay(self, aggregate_id: str | None = None) -> list[Event]:
        """按聚合 ID 回放事件（支持 task_id/deal_id/user_id 三种聚合）。"""
        with self._session() as session:
            stmt = select(EventModel).order_by(EventModel.event_id)
            if aggregate_id is not None:
                stmt = stmt.where(
                    or_(
                        EventModel.task_id == aggregate_id,
                        EventModel.deal_id == aggregate_id,
                        EventModel.user_id == aggregate_id,
                    )
                )
            models = session.execute(stmt).scalars().all()
            return [event_from_orm(m) for m in models]
