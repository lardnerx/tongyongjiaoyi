"""规则配置仓储。

提供两套实现：
- InMemoryRuleRepository：开发与测试用
- PostgresRuleRepository：生产用，基于 SQLAlchemy session

仓储接口返回纯 dict（不暴露 ORM 模型），降低上层对 ORM 的耦合。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class RuleRepositoryProtocol(Protocol):
    """规则仓储协议。"""

    def find_by_key(self, rule_key: str) -> dict[str, Any] | None: ...

    def list_all(self) -> list[dict[str, Any]]: ...

    def list_by_category(self, category: str) -> list[dict[str, Any]]: ...

    def upsert(
        self,
        rule_key: str,
        rule_value: Any,
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None: ...

    def history(self, rule_key: str) -> list[dict[str, Any]]: ...


# 仓储协议别名：与现有 Repository 命名约定一致（如 TaskRepository）。
RuleRepository = RuleRepositoryProtocol


class InMemoryRuleRepository:
    """内存规则仓储（开发与测试用）。"""

    def __init__(self) -> None:
        self._rules: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []

    def find_by_key(self, rule_key: str) -> dict[str, Any] | None:
        rule = self._rules.get(rule_key)
        return dict(rule) if rule else None

    def list_all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rules.values()]

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rules.values() if r["category"] == category]

    def upsert(
        self,
        rule_key: str,
        rule_value: dict[str, Any],
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None:
        old = self._rules.get(rule_key)
        old_value = old["rule_value"] if old else None
        new_version = (old["version"] + 1) if old else 1
        now = datetime.utcnow()
        self._rules[rule_key] = {
            "rule_key": rule_key,
            "rule_value": dict(rule_value) if isinstance(rule_value, dict) else rule_value,
            "description": description or (old["description"] if old else None),
            "category": category,
            "version": new_version,
            "updated_by": updated_by,
            "updated_at": now,
        }
        self._history.append(
            {
                "history_id": len(self._history) + 1,
                "rule_key": rule_key,
                "old_value": dict(old_value) if isinstance(old_value, dict) else old_value,
                "new_value": dict(rule_value) if isinstance(rule_value, dict) else rule_value,
                "changed_by": updated_by,
                "changed_at": now,
                "change_reason": reason,
            }
        )

    def history(self, rule_key: str) -> list[dict[str, Any]]:
        return [dict(h) for h in self._history if h["rule_key"] == rule_key]


class PostgresRuleRepository:
    """PostgreSQL 规则仓储（生产用）。"""

    def __init__(self, session_factory) -> None:
        """session_factory: SQLAlchemy sessionmaker。"""
        self._session_factory = session_factory

    def find_by_key(self, rule_key: str) -> dict[str, Any] | None:
        from umcp_core.shared.rules.models import BusinessRuleModel

        with self._session_factory() as session:
            m = session.get(BusinessRuleModel, rule_key)
            if m is None:
                return None
            return self._to_dict(m)

    def list_all(self) -> list[dict[str, Any]]:
        from umcp_core.shared.rules.models import BusinessRuleModel

        with self._session_factory() as session:
            rows = session.query(BusinessRuleModel).all()
            return [self._to_dict(m) for m in rows]

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        from umcp_core.shared.rules.models import BusinessRuleModel

        with self._session_factory() as session:
            rows = session.query(BusinessRuleModel).filter_by(category=category).all()
            return [self._to_dict(m) for m in rows]

    def upsert(
        self,
        rule_key: str,
        rule_value: Any,
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None:
        from umcp_core.shared.rules.models import BusinessRuleHistoryModel, BusinessRuleModel

        with self._session_factory() as session:
            m = session.get(BusinessRuleModel, rule_key)
            old_value = m.rule_value if m else None
            now = datetime.utcnow()
            if m is None:
                m = BusinessRuleModel(
                    rule_key=rule_key,
                    rule_value=rule_value,
                    description=description,
                    category=category,
                    version=1,
                    updated_by=updated_by,
                    updated_at=now,
                )
                session.add(m)
            else:
                m.rule_value = rule_value
                m.version = m.version + 1
                m.updated_by = updated_by
                m.updated_at = now
                if description is not None:
                    m.description = description
            session.add(
                BusinessRuleHistoryModel(
                    rule_key=rule_key,
                    old_value=old_value,
                    new_value=rule_value,
                    changed_by=updated_by,
                    changed_at=now,
                    change_reason=reason,
                )
            )
            session.commit()

    def history(self, rule_key: str) -> list[dict[str, Any]]:
        from umcp_core.shared.rules.models import BusinessRuleHistoryModel

        with self._session_factory() as session:
            rows = (
                session.query(BusinessRuleHistoryModel)
                .filter_by(rule_key=rule_key)
                .order_by(BusinessRuleHistoryModel.history_id)
                .all()
            )
            return [
                {
                    "history_id": h.history_id,
                    "rule_key": h.rule_key,
                    "old_value": h.old_value,
                    "new_value": h.new_value,
                    "changed_by": h.changed_by,
                    "changed_at": h.changed_at,
                    "change_reason": h.change_reason,
                }
                for h in rows
            ]

    @staticmethod
    def _to_dict(m) -> dict[str, Any]:
        return {
            "rule_key": m.rule_key,
            "rule_value": m.rule_value,
            "description": m.description,
            "category": m.category,
            "version": m.version,
            "updated_by": m.updated_by,
            "updated_at": m.updated_at,
        }
