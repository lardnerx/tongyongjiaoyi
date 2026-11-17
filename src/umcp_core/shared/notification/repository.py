"""通知仓储：ORM 模型 + 内存/PostgreSQL 两套实现。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base
from umcp_core.shared.notification.base import Notification


class NotificationRepositoryProtocol(Protocol):
    """站内通知仓储协议。"""

    def save(self, notification: Notification) -> int: ...

    def list_by_user(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def count_unread(self, user_id: str) -> int: ...

    def mark_read(self, user_id: str, notification_id: int) -> bool: ...

    def mark_all_read(self, user_id: str) -> int: ...


NotificationRepository = NotificationRepositoryProtocol


class NotificationModel(Base):
    """站内通知表。"""

    __tablename__ = "notifications"

    notification_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NotificationTemplateModel(Base):
    """通知模板表（后台可配置）。"""

    __tablename__ = "notification_templates"

    template_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(32), nullable=False)
    channels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    title_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InMemoryNotificationRepository:
    """内存通知仓储（开发与测试用）。"""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._next_id = 1

    def save(self, notification: Notification) -> int:
        notification_id = self._next_id
        self._next_id += 1
        self._items.append(
            {
                "notification_id": notification_id,
                "user_id": notification.user_id,
                "type": notification.event_type,
                "title": notification.title,
                "body": notification.body,
                "channels": list(notification.channels),
                "read_at": None,
                "created_at": notification.created_at,
            }
        )
        return notification_id

    def list_by_user(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self._items if r["user_id"] == user_id]
        if unread_only:
            rows = [r for r in rows if r["read_at"] is None]
        rows.sort(key=lambda r: r["notification_id"], reverse=True)
        return rows[offset : offset + limit]

    def count_unread(self, user_id: str) -> int:
        return sum(
            1 for r in self._items if r["user_id"] == user_id and r["read_at"] is None
        )

    def mark_read(self, user_id: str, notification_id: int) -> bool:
        for r in self._items:
            if r["notification_id"] == notification_id and r["user_id"] == user_id:
                if r["read_at"] is None:
                    r["read_at"] = datetime.utcnow()
                return True
        return False

    def mark_all_read(self, user_id: str) -> int:
        now = datetime.utcnow()
        count = 0
        for r in self._items:
            if r["user_id"] == user_id and r["read_at"] is None:
                r["read_at"] = now
                count += 1
        return count


class PostgresNotificationRepository:
    """PostgreSQL 通知仓储（生产用）。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def save(self, notification: Notification) -> int:
        with self._session_factory() as session:
            m = NotificationModel(
                user_id=notification.user_id,
                type=notification.event_type,
                title=notification.title,
                body=notification.body,
                channels=list(notification.channels),
                read_at=None,
                created_at=notification.created_at,
            )
            session.add(m)
            session.commit()
            return m.notification_id

    def list_by_user(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            q = session.query(NotificationModel).filter_by(user_id=user_id)
            if unread_only:
                q = q.filter(NotificationModel.read_at.is_(None))
            rows = (
                q.order_by(NotificationModel.notification_id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [self._to_dict(m) for m in rows]

    def count_unread(self, user_id: str) -> int:
        with self._session_factory() as session:
            total = (
                session.query(func.count(NotificationModel.notification_id))
                .filter_by(user_id=user_id)
                .filter(NotificationModel.read_at.is_(None))
                .scalar()
            )
            return int(total or 0)

    def mark_read(self, user_id: str, notification_id: int) -> bool:
        with self._session_factory() as session:
            m = (
                session.query(NotificationModel)
                .filter_by(notification_id=notification_id, user_id=user_id)
                .first()
            )
            if m is None:
                return False
            if m.read_at is None:
                m.read_at = datetime.utcnow()
                session.commit()
            return True

    def mark_all_read(self, user_id: str) -> int:
        with self._session_factory() as session:
            count = (
                session.query(NotificationModel)
                .filter_by(user_id=user_id)
                .filter(NotificationModel.read_at.is_(None))
                .update({"read_at": datetime.utcnow()}, synchronize_session=False)
            )
            session.commit()
            return int(count or 0)

    @staticmethod
    def _to_dict(m: NotificationModel) -> dict[str, Any]:
        return {
            "notification_id": m.notification_id,
            "user_id": m.user_id,
            "type": m.type,
            "title": m.title,
            "body": m.body,
            "channels": m.channels or [],
            "read_at": m.read_at,
            "created_at": m.created_at,
        }
