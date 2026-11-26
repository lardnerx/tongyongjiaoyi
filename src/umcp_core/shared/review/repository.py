"""评价记录仓储。

评价是跨行业的通用能力（订单完成后双方互评），因此放在 shared 层，
由插件在业务路由中调用。仓储以 dict 承载记录，字段与 HTTP 契约一致：

    review_id / task_id / reviewer_id / reviewer_role / evaluatee_id /
    ratings / comment / created_at

同一订单下每个角色只允许一条评价（task_id, reviewer_role 唯一），
仓储层会拒绝重复写入并抛出 ValueError。
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class ReviewModel(Base):
    """评价表。"""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("task_id", "reviewer_role", name="uq_reviews_task_role"),
    )

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluatee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ratings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InMemoryReviewRepository:
    """内存评价仓储（开发与测试用）。"""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def save(self, review: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for existing in self._items.values():
                if (
                    existing["task_id"] == review["task_id"]
                    and existing["reviewer_role"] == review["reviewer_role"]
                ):
                    raise ValueError("该角色已评价过此订单")
            self._items[review["review_id"]] = copy.deepcopy(review)
            return copy.deepcopy(review)

    def find_by_id(self, review_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(review_id)
            return copy.deepcopy(item) if item else None

    def find_by_task(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                copy.deepcopy(item)
                for item in self._items.values()
                if item["task_id"] == task_id
            ]

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(item) for item in self._items.values()]


class PostgresReviewRepository:
    """PG 评价仓储。"""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def save(self, review: dict[str, Any]) -> dict[str, Any]:
        with self._session_factory() as session:
            model = ReviewModel(
                review_id=review["review_id"],
                task_id=review["task_id"],
                reviewer_id=review["reviewer_id"],
                reviewer_role=review["reviewer_role"],
                evaluatee_id=review["evaluatee_id"],
                ratings=review.get("ratings") or {},
                comment=review.get("comment", ""),
                created_at=review.get("created_at") or datetime.utcnow(),
            )
            session.add(model)
            try:
                session.commit()
            except IntegrityError as e:
                session.rollback()
                raise ValueError("该角色已评价过此订单") from e
            return self._to_dict(model)

    def find_by_id(self, review_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            model = session.get(ReviewModel, review_id)
            return self._to_dict(model) if model else None

    def find_by_task(self, task_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = (
                session.query(ReviewModel)
                .filter_by(task_id=task_id)
                .order_by(ReviewModel.created_at)
                .all()
            )
            return [self._to_dict(m) for m in rows]

    def list_all(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.query(ReviewModel).all()
            return [self._to_dict(m) for m in rows]

    @staticmethod
    def _to_dict(model: ReviewModel) -> dict[str, Any]:
        return {
            "review_id": model.review_id,
            "task_id": model.task_id,
            "reviewer_id": model.reviewer_id,
            "reviewer_role": model.reviewer_role,
            "evaluatee_id": model.evaluatee_id,
            "ratings": model.ratings or {},
            "comment": model.comment or "",
            "created_at": model.created_at,
        }
