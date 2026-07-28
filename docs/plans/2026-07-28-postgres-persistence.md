# 阶段五 A：持久化与生产化 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将全内存协议栈改造为 PostgreSQL 持久化，支持重启恢复与复合任务智能恢复。

**架构：** 双层架构（领域对象 + ORM 模型分离），PostgreSQL + SQLAlchemy 2.0，混合事件存储（业务表存当前状态 + events 表存审计日志），复合任务启动时智能恢复（DRAFT 重派 / IN_PROGRESS 标记待超时）。

**技术栈：** PostgreSQL 16、SQLAlchemy 2.0、Alembic、psycopg3、pytest

**规格文档：** `docs/specs/2026-07-28-postgres-persistence-design.md`

---

## 文件结构

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/umcp_core/repositories/postgres/__init__.py` | 子包入口，导出公共类 |
| `src/umcp_core/repositories/postgres/models.py` | 7 个 SQLAlchemy ORM 模型 |
| `src/umcp_core/repositories/postgres/converters.py` | 领域对象 ↔ ORM 模型转换器（纯函数） |
| `src/umcp_core/repositories/postgres/task_repo.py` | PostgresTaskRepository |
| `src/umcp_core/repositories/postgres/resource_repo.py` | PostgresResourceRepository |
| `src/umcp_core/repositories/postgres/deal_repo.py` | PostgresDealRepository |
| `src/umcp_core/repositories/postgres/user_repo.py` | PostgresUserRepository |
| `src/umcp_core/repositories/postgres/trust_repo.py` | PostgresTrustRepository（含 domain 隔离） |
| `src/umcp_core/repositories/postgres/event_repo.py` | PostgresEventRepository（含 replay） |
| `src/umcp_core/repositories/postgres/bundle.py` | PostgresRepositoryBundle（入口套件） |
| `migrations/alembic.ini` | Alembic 配置 |
| `migrations/env.py` | Alembic 环境（从 DATABASE_URL 读取） |
| `migrations/script.py.mako` | Alembic 迁移模板 |
| `migrations/versions/001_init_schema.py` | 初始 schema（7 张表 + 索引） |
| `docker-compose.yml` | PostgreSQL 容器 |
| `tests/conftest.py` | pytest fixture（pg_engine/pg_session/pg_bundle/server_with_pg） |
| `tests/test_postgres_converters.py` | L1 转换器单元测试 |
| `tests/test_postgres_repos.py` | L2 仓储 CRUD 测试 |
| `tests/test_recovery.py` | L3 复合任务恢复测试 |
| `tests/test_persistence_e2e.py` | L4 端到端持久化测试 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `src/umcp_core/layers/l5/trust.py` | TrustProfile 和 Evaluation 加 `domain_tag` 字段（默认空字符串，向后兼容） |
| `src/umcp_core/repositories/interfaces.py` | TrustRepository 新增 `find_profile_by_domain(user_id, domain_tag)` 抽象方法 |
| `src/umcp_core/repositories/in_memory.py` | InMemoryTrustRepository 实现 `find_profile_by_domain`，存储改为按 (user_id, domain_tag) 索引 |
| `src/umcp_core/server.py` | 新增 `use_postgres_repositories`/`recover_composite_tasks`/`_recover_single_composite`/`_register_composite_bridge`/`_persist_composite_atomic`/`dispose`；`start()` 集成恢复；`execute_composite` 改造持久化 |
| `pyproject.toml` | 新增 `postgres` 和 `dev` 可选依赖 |

---

## 任务 1：领域对象扩展 + ORM 模型 + 转换器

**文件：**
- 修改：`src/umcp_core/layers/l5/trust.py`
- 创建：`src/umcp_core/repositories/postgres/__init__.py`
- 创建：`src/umcp_core/repositories/postgres/models.py`
- 创建：`src/umcp_core/repositories/postgres/converters.py`
- 测试：`tests/test_postgres_converters.py`

### 步骤 1.1：给 TrustProfile 和 Evaluation 加 domain_tag 字段

- [ ] 修改 `src/umcp_core/layers/l5/trust.py`

在 `Evaluation` dataclass 末尾加 `domain_tag: str = ""` 字段：

```python
@dataclass
class Evaluation:
    """评价记录。"""

    evaluator_id: str
    evaluatee_id: str
    task_id: str
    ratings: dict[str, float] = field(default_factory=dict)
    comment: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    domain_tag: str = ""  # 新增：用于 domain 隔离持久化
```

在 `TrustProfile` dataclass 末尾加 `domain_tag: str = ""` 字段：

```python
@dataclass
class TrustProfile:
    """多维信誉画像。"""

    user_id: str
    dimension_scores: dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    domain_tag: str = ""  # 新增：用于 domain 隔离持久化

    # ... 已有方法不变
```

- [ ] 运行现有测试验证零回归

运行：`pytest tests/ --ignore=tests/test_postgres_repos.py --ignore=tests/test_recovery.py --ignore=tests/test_persistence_e2e.py -x -q`
预期：PASS（442 passed，新字段有默认值，向后兼容）

- [ ] Commit

```bash
git add src/umcp_core/layers/l5/trust.py
git commit -m "refactor(trust): TrustProfile 和 Evaluation 加 domain_tag 字段（向后兼容）"
```

### 步骤 1.2：创建 ORM 模型

- [ ] 创建 `src/umcp_core/repositories/postgres/__init__.py`（空文件）

- [ ] 创建 `src/umcp_core/repositories/postgres/models.py`

```python
"""SQLAlchemy 2.0 ORM 模型，对应 7 张数据库表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


class TaskModel(Base):
    """任务表（含复合任务和子任务，用 parent_task_id 建立层级）。"""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    demander_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_tag: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custom_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ResourceModel(Base):
    """资源表。"""

    __tablename__ = "resources"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_tag: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class DealModel(Base):
    """交易表。"""

    __tablename__ = "deals"

    deal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    demander_id: Mapped[str] = mapped_column(String(64), nullable=False)
    final_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserModel(Base):
    """用户表。"""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    user_type: Mapped[str] = mapped_column(String(32), nullable=False)
    roles: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TrustProfileModel(Base):
    """信任档案表（按 domain 隔离）。"""

    __tablename__ = "trust_profiles"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_tag: Mapped[str] = mapped_column(String(32), primary_key=True)
    overall_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TrustEvaluationModel(Base):
    """评价记录表。"""

    __tablename__ = "trust_evaluations"

    evaluator_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluatee_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_tag: Mapped[str] = mapped_column(String(32), nullable=False)
    ratings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EventModel(Base):
    """事件日志表（用于审计与回放）。"""

    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_layer: Mapped[str] = mapped_column(String(16), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CompositeDependencyModel(Base):
    """复合任务 DAG 依赖关系表。"""

    __tablename__ = "composite_dependencies"

    composite_task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subtask_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(String(64), primary_key=True)
```

### 步骤 1.3：创建转换器

- [ ] 创建 `src/umcp_core/repositories/postgres/converters.py`

```python
"""领域对象 ↔ ORM 模型转换器（纯函数）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.core.deal import Deal
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource
from umcp_core.core.task import CustomTask, PackageTask, StandardTask, Task, TaskStatus
from umcp_core.core.composite_task import CompositeTask
from umcp_core.events.bus import Event
from umcp_core.layers.l5 import Evaluation, TrustProfile
from umcp_core.repositories.postgres.models import (
    CompositeDependencyModel,
    DealModel,
    EventModel,
    ResourceModel,
    TaskModel,
    TrustEvaluationModel,
    TrustProfileModel,
    UserModel,
)

# task_type → 领域类的映射
_TASK_TYPE_REGISTRY: dict[str, type[Task]] = {
    "standard": StandardTask,
    "custom": CustomTask,
    "package": PackageTask,
    "composite": CompositeTask,
}


# ------------------------------------------------------------------
# Task 转换器
# ------------------------------------------------------------------


def task_to_orm(task: Task) -> TaskModel:
    """领域 Task → ORM TaskModel。"""
    parent_task_id = getattr(task, "parent_task_id", None)
    return TaskModel(
        task_id=task.task_id,
        task_type=task.task_type(),
        demander_id=task.demander_id,
        domain_tag=task.domain_tag.value,
        title=task.title,
        description=task.description,
        status=task.status,
        supplier_id=getattr(task, "supplier_id", None),
        assigned_resource_id=task.assigned_resource_id,
        parent_task_id=parent_task_id,
        custom_fields=task.custom_fields,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def task_from_orm(model: TaskModel) -> Task:
    """ORM TaskModel → 领域 Task（按 task_type 重建对应子类）。

    注意：CompositeTask 的 dependencies 和 subtasks 需要额外查询重建，
    此函数只重建基本字段，使用 composite_task_from_orm 重建完整 CompositeTask。
    """
    cls = _TASK_TYPE_REGISTRY.get(model.task_type, StandardTask)
    task = cls(
        demander_id=model.demander_id,
        domain_tag=DomainTag.of(model.domain_tag),
        title=model.title or "",
        description=model.description or "",
    )
    task.task_id = model.task_id
    task.status = model.status
    task.assigned_resource_id = model.assigned_resource_id
    task.custom_fields = model.custom_fields or {}
    task.created_at = model.created_at
    task.updated_at = model.updated_at
    return task


def composite_task_from_orm(
    model: TaskModel,
    dependencies: dict[str, list[str]],
    subtasks: list[Task],
) -> CompositeTask:
    """重建 CompositeTask（含 dependencies 和 subtasks）。"""
    composite = task_from_orm(model)
    # 直接设置属性（CompositeTask 在 __init__ 后已校验过 DAG，
    # 恢复时跳过校验以接受已持久化的状态）
    composite.subtasks = subtasks
    composite.dependencies = dependencies
    return composite


# ------------------------------------------------------------------
# Resource 转换器
# ------------------------------------------------------------------


def _capability_to_dict(cap: Capability) -> dict[str, Any]:
    return {
        "type": cap.type,
        "name": cap.name,
        "value": cap.value,
        "verified": cap.verified,
        "expiry": cap.expiry.isoformat() if cap.expiry else None,
    }


def _capability_from_dict(data: dict[str, Any]) -> Capability:
    from datetime import datetime

    expiry = None
    if data.get("expiry"):
        expiry = datetime.fromisoformat(data["expiry"])
    return Capability(
        type=data["type"],
        name=data["name"],
        value=data.get("value", ""),
        verified=data.get("verified", False),
        expiry=expiry,
    )


def resource_to_orm(resource: Resource) -> ResourceModel:
    """领域 Resource → ORM ResourceModel。"""
    return ResourceModel(
        resource_id=resource.resource_id,
        supplier_id=resource.supplier_id,
        domain_tag=resource.domain_tag.value,
        resource_type=resource.resource_type(),
        status=resource.status,
        capabilities=[_capability_to_dict(c) for c in resource.capabilities],
        metadata=resource.metadata,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


def resource_from_orm(model: ResourceModel) -> Resource:
    """ORM ResourceModel → 领域 Resource。

    注意：Resource 是抽象类，需要按 resource_type 重建子类。
    此函数创建一个通用 Resource 子类实例（用 SimpleResource 兜底）。
    实际应用中应注册 resource_type → cls 映射。
    """
    from umcp_core.core.resource import Resource as ResourceBase

    # 创建一个简单的 Resource 子类实例（避免依赖具体插件）
    class _GenericResource(ResourceBase):
        def resource_type(self) -> str:
            return model.resource_type

    resource = _GenericResource(
        supplier_id=model.supplier_id,
        domain_tag=DomainTag.of(model.domain_tag),
        resource_id=model.resource_id,
        capabilities=[_capability_from_dict(c) for c in (model.capabilities or [])],
        metadata=model.metadata or {},
    )
    resource.status = model.status
    resource.created_at = model.created_at
    resource.updated_at = model.updated_at
    return resource


# ------------------------------------------------------------------
# Deal 转换器
# ------------------------------------------------------------------


def deal_to_orm(deal: Deal) -> DealModel:
    """领域 Deal → ORM DealModel。"""
    return DealModel(
        deal_id=deal.deal_id,
        task_id=deal.task_id,
        resource_id=deal.resource_id,
        supplier_id=deal.supplier_id,
        demander_id=deal.demander_id,
        final_amount=deal.final_amount,
        status=deal.status,
        completed_at=deal.completed_at,
        metadata=deal.metadata,
        created_at=deal.matched_at,
        updated_at=deal.completed_at or deal.matched_at,
    )


def deal_from_orm(model: DealModel) -> Deal:
    """ORM DealModel → 领域 Deal。"""
    deal = Deal(
        task_id=model.task_id,
        resource_id=model.resource_id,
        demander_id=model.demander_id,
        supplier_id=model.supplier_id,
        deal_id=model.deal_id,
        final_amount=float(model.final_amount) if model.final_amount is not None else None,
        metadata=model.metadata or {},
    )
    deal.status = model.status
    deal.matched_at = model.created_at
    deal.completed_at = model.completed_at
    return deal


# ------------------------------------------------------------------
# User 转换器
# ------------------------------------------------------------------


def user_to_orm(user: Any) -> UserModel:
    """领域 User → ORM UserModel。

    注意：User 是抽象类，roles 和 active_role 序列化为 dict。
    """
    roles_data = {}
    for role_type, role in getattr(user, "roles", {}).items():
        perms = getattr(role, "permissions", None)
        perm_list = list(perms) if perms else []
        roles_data[role_type] = {"permissions": perm_list}

    return UserModel(
        user_id=user.user_id,
        name=user.name,
        user_type=user.active_role.role_type if getattr(user, "active_role", None) else "unknown",
        roles=roles_data,
        metadata=getattr(user, "metadata", {}),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def user_from_orm(model: UserModel) -> Any:
    """ORM UserModel → 领域 User。

    注意：User 是抽象类，需要按 user_type 重建子类。
    此函数创建一个通用 User 子类实例。
    """
    from umcp_core.core.base import Demander, PermissionSet, Supplier, User as UserBase

    class _GenericUser(UserBase):
        def __init__(self, user_id: str, name: str, metadata: dict | None = None) -> None:
            super().__init__(user_id=user_id, name=name, metadata=metadata)

        def authenticate(self, credential: Any) -> bool:
            return True

    user = _GenericUser(
        user_id=model.user_id,
        name=model.name,
        metadata=model.metadata or {},
    )
    # 恢复 roles
    for role_type, role_data in (model.roles or {}).items():
        perms = PermissionSet(set(role_data.get("permissions", [])))
        if role_type == "demander":
            class _RestoredDemander(Demander):
                @property
                def permissions(self) -> PermissionSet:
                    return perms

            user.add_role(_RestoredDemander())
        elif role_type == "supplier":
            class _RestoredSupplier(Supplier):
                @property
                def permissions(self) -> PermissionSet:
                    return perms

            user.add_role(_RestoredSupplier())
    return user


# ------------------------------------------------------------------
# TrustProfile 转换器
# ------------------------------------------------------------------


def trust_profile_to_orm(profile: TrustProfile) -> TrustProfileModel:
    """领域 TrustProfile → ORM TrustProfileModel。"""
    return TrustProfileModel(
        user_id=profile.user_id,
        domain_tag=profile.domain_tag,
        overall_score=profile.overall_score,
        dimension_scores=profile.dimension_scores,
        last_updated=profile.last_updated,
    )


def trust_profile_from_orm(model: TrustProfileModel) -> TrustProfile:
    """ORM TrustProfileModel → 领域 TrustProfile。"""
    return TrustProfile(
        user_id=model.user_id,
        dimension_scores=model.dimension_scores or {},
        overall_score=float(model.overall_score),
        last_updated=model.last_updated,
        domain_tag=model.domain_tag,
    )


# ------------------------------------------------------------------
# Evaluation 转换器
# ------------------------------------------------------------------


def evaluation_to_orm(evaluation: Evaluation) -> TrustEvaluationModel:
    """领域 Evaluation → ORM TrustEvaluationModel。"""
    return TrustEvaluationModel(
        evaluator_id=evaluation.evaluator_id,
        evaluatee_id=evaluation.evaluatee_id,
        task_id=evaluation.task_id,
        domain_tag=evaluation.domain_tag,
        ratings=evaluation.ratings,
        comment=evaluation.comment,
        created_at=evaluation.created_at,
    )


def evaluation_from_orm(model: TrustEvaluationModel) -> Evaluation:
    """ORM TrustEvaluationModel → 领域 Evaluation。"""
    return Evaluation(
        evaluator_id=model.evaluator_id,
        evaluatee_id=model.evaluatee_id,
        task_id=model.task_id,
        ratings=model.ratings or {},
        comment=model.comment or "",
        created_at=model.created_at,
        domain_tag=model.domain_tag,
    )


# ------------------------------------------------------------------
# Event 转换器
# ------------------------------------------------------------------


def event_to_orm(event: Event) -> EventModel:
    """领域 Event → ORM EventModel。"""
    return EventModel(
        event_type=event.type.value if hasattr(event.type, "value") else str(event.type),
        source_layer=event.source_layer,
        task_id=event.payload.get("task_id"),
        deal_id=event.payload.get("deal_id"),
        user_id=event.payload.get("user_id"),
        payload=event.payload,
        created_at=datetime.utcfromtimestamp(event.timestamp),
    )


def event_from_orm(model: EventModel) -> Event:
    """ORM EventModel → 领域 Event。"""
    from umcp_core.events.types import EventType

    event_type_str = model.event_type
    try:
        event_type = EventType(event_type_str)
    except ValueError:
        event_type = event_type_str  # 保留原始字符串

    return Event(
        type=event_type,
        source_layer=model.source_layer,
        payload=model.payload or {},
        timestamp=model.created_at.timestamp(),
    )


# ------------------------------------------------------------------
# CompositeDependency 转换器
# ------------------------------------------------------------------


def dependencies_to_orm(
    composite_task_id: str, dependencies: dict[str, list[str]]
) -> list[CompositeDependencyModel]:
    """依赖关系 dict → ORM CompositeDependencyModel 列表。"""
    models = []
    for subtask_id, deps in dependencies.items():
        for dep_id in deps:
            models.append(
                CompositeDependencyModel(
                    composite_task_id=composite_task_id,
                    subtask_id=subtask_id,
                    depends_on_id=dep_id,
                )
            )
    return models


def dependencies_from_orm(models: list[CompositeDependencyModel]) -> dict[str, list[str]]:
    """ORM CompositeDependencyModel 列表 → 依赖关系 dict。"""
    deps: dict[str, list[str]] = {}
    for model in models:
        deps.setdefault(model.subtask_id, []).append(model.depends_on_id)
    return deps
```

### 步骤 1.4：编写转换器单元测试

- [ ] 创建 `tests/test_postgres_converters.py`

```python
"""L1: 转换器单元测试。

验证领域对象 ↔ ORM 模型双向转换的正确性。
不依赖数据库，纯函数测试。
"""

from __future__ import annotations

import pytest
from datetime import datetime

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus, CustomTask
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l5 import Evaluation, TrustProfile
from umcp_core.repositories.postgres.converters import (
    composite_task_from_orm,
    deal_from_orm,
    deal_to_orm,
    dependencies_from_orm,
    dependencies_to_orm,
    evaluation_from_orm,
    evaluation_to_orm,
    event_from_orm,
    event_to_orm,
    task_from_orm,
    task_to_orm,
    trust_profile_from_orm,
    trust_profile_to_orm,
)
from umcp_core.repositories.postgres.models import (
    DealModel,
    EventModel,
    TaskModel,
    TrustEvaluationModel,
    TrustProfileModel,
)


class TestTaskConverter:
    def test_standard_task_roundtrip(self):
        """StandardTask to_orm → from_orm 应保留所有字段。"""
        task = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="打车到机场",
            description="紧急",
        )
        task.task_id = "task-123"
        task.status = TaskStatus.MATCHING
        task.assigned_resource_id = "res-456"
        task.custom_fields = {"pickup": "中关村"}
        task.created_at = datetime(2026, 7, 28, 10, 0, 0)
        task.updated_at = datetime(2026, 7, 28, 10, 5, 0)

        model = task_to_orm(task)
        assert model.task_id == "task-123"
        assert model.task_type == "standard"
        assert model.demander_id == "user-1"
        assert model.domain_tag == "ride_hailing"
        assert model.status == TaskStatus.MATCHING
        assert model.assigned_resource_id == "res-456"
        assert model.custom_fields == {"pickup": "中关村"}

        restored = task_from_orm(model)
        assert restored.task_id == "task-123"
        assert restored.task_type() == "standard"
        assert restored.demander_id == "user-1"
        assert restored.domain_tag.value == "ride_hailing"
        assert restored.status == TaskStatus.MATCHING
        assert restored.assigned_resource_id == "res-456"
        assert restored.custom_fields == {"pickup": "中关村"}

    def test_custom_task_roundtrip(self):
        """CustomTask to_orm → from_orm 应重建为 CustomTask。"""
        task = CustomTask(
            demander_id="user-2",
            domain_tag=DomainTag.of("group_buying"),
            title="设计服务",
        )
        model = task_to_orm(task)
        assert model.task_type == "custom"

        restored = task_from_orm(model)
        assert isinstance(restored, CustomTask)
        assert restored.task_type() == "custom"

    def test_composite_task_roundtrip(self):
        """CompositeTask 重建需额外传入 dependencies 和 subtasks。"""
        sub_a = StandardTask(
            demander_id="user-1", domain_tag=DomainTag.of("ride_hailing")
        )
        sub_b = StandardTask(
            demander_id="user-1", domain_tag=DomainTag.of("ride_hailing")
        )
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )

        model = task_to_orm(composite)
        assert model.task_type == "composite"

        # from_orm 只重建基本字段
        basic = task_from_orm(model)
        assert isinstance(basic, CompositeTask)

        # composite_task_from_orm 重建完整
        dep_models = dependencies_to_orm(
            composite.task_id, {sub_b.task_id: [sub_a.task_id]}
        )
        deps = dependencies_from_orm(dep_models)
        full = composite_task_from_orm(model, deps, [sub_a, sub_b])
        assert len(full.subtasks) == 2
        assert full.dependencies == {sub_b.task_id: [sub_a.task_id]}


class TestDealConverter:
    def test_deal_roundtrip(self):
        deal = Deal(
            task_id="task-1",
            resource_id="res-1",
            demander_id="user-1",
            supplier_id="sup-1",
            deal_id="deal-1",
            final_amount=99.50,
            metadata={"payment_method": "alipay"},
        )
        deal.status = DealStatus.ACTIVE

        model = deal_to_orm(deal)
        assert model.deal_id == "deal-1"
        assert model.final_amount == 99.50
        assert model.status == DealStatus.ACTIVE

        restored = deal_from_orm(model)
        assert restored.deal_id == "deal-1"
        assert restored.final_amount == 99.50
        assert restored.status == DealStatus.ACTIVE
        assert restored.metadata == {"payment_method": "alipay"}


class TestTrustProfileConverter:
    def test_trust_profile_roundtrip_with_domain(self):
        profile = TrustProfile(
            user_id="user-1",
            dimension_scores={"delivery": 0.9, "quality": 0.8},
            overall_score=0.85,
            domain_tag="ride_hailing",
        )

        model = trust_profile_to_orm(profile)
        assert model.user_id == "user-1"
        assert model.domain_tag == "ride_hailing"
        assert model.overall_score == 0.85

        restored = trust_profile_from_orm(model)
        assert restored.user_id == "user-1"
        assert restored.domain_tag == "ride_hailing"
        assert restored.overall_score == 0.85
        assert restored.dimension_scores == {"delivery": 0.9, "quality": 0.8}


class TestEvaluationConverter:
    def test_evaluation_roundtrip_with_domain(self):
        evaluation = Evaluation(
            evaluator_id="user-1",
            evaluatee_id="user-2",
            task_id="task-1",
            ratings={"quality": 0.9},
            comment="好评",
            domain_tag="ride_hailing",
        )

        model = evaluation_to_orm(evaluation)
        assert model.evaluator_id == "user-1"
        assert model.domain_tag == "ride_hailing"

        restored = evaluation_from_orm(model)
        assert restored.evaluator_id == "user-1"
        assert restored.domain_tag == "ride_hailing"
        assert restored.ratings == {"quality": 0.9}


class TestEventConverter:
    def test_event_roundtrip(self):
        event = Event(
            type=EventType.TASK_PUBLISHED,
            source_layer="L2",
            payload={"task_id": "task-1", "extra": "data"},
        )

        model = event_to_orm(event)
        assert model.event_type == "task.published"
        assert model.task_id == "task-1"
        assert model.payload["extra"] == "data"

        restored = event_from_orm(model)
        assert restored.type == EventType.TASK_PUBLISHED
        assert restored.payload["task_id"] == "task-1"
        assert restored.payload["extra"] == "data"


class TestDependenciesConverter:
    def test_dependencies_roundtrip(self):
        deps = {"b": ["a"], "c": ["a", "b"]}
        models = dependencies_to_orm("composite-1", deps)
        assert len(models) == 3

        restored = dependencies_from_orm(models)
        assert sorted(restored["b"]) == ["a"]
        assert sorted(restored["c"]) == ["a", "b"]
```

- [ ] 运行测试验证通过

运行：`pytest tests/test_postgres_converters.py -v`
预期：PASS（10 个测试）

- [ ] Commit

```bash
git add src/umcp_core/repositories/postgres/__init__.py src/umcp_core/repositories/postgres/models.py src/umcp_core/repositories/postgres/converters.py tests/test_postgres_converters.py
git commit -m "feat(postgres): ORM 模型与转换器（7 张表 + 6 对转换器）"
```

---

## 任务 2：PostgresTaskRepository

**文件：**
- 创建：`src/umcp_core/repositories/postgres/task_repo.py`
- 测试：`tests/test_postgres_repos.py`（新建，本任务只写 TaskRepository 部分）

### 步骤 2.1：编写 TaskRepository 失败测试

- [ ] 创建 `tests/test_postgres_repos.py`

```python
"""L2: PostgreSQL 仓储 CRUD 测试。

需要 PostgreSQL 服务。通过 TEST_DATABASE_URL 环境变量配置连接。
默认连接 docker-compose 提供的 umcp_dev 数据库。
"""

from __future__ import annotations

import os
import pytest
from datetime import datetime

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus, CustomTask

pytestmark = pytest.mark.postgres


@pytest.fixture
def task_repo(pg_bundle):
    return pg_bundle.task_repo


class TestPostgresTaskRepository:
    def test_save_and_find_by_id(self, task_repo):
        task = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="打车",
        )
        task_id = task.task_id
        task_repo.save(task)

        found = task_repo.find_by_id(task_id)
        assert found is not None
        assert found.task_id == task_id
        assert found.demander_id == "user-1"
        assert found.status == TaskStatus.DRAFT
        assert found.title == "打车"

    def test_find_by_id_nonexistent_returns_none(self, task_repo):
        assert task_repo.find_by_id("nonexistent-id") is None

    def test_save_upsert(self, task_repo):
        """同一 task_id 二次 save 应更新而非插入。"""
        task = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="原标题",
        )
        task_repo.save(task)

        task.title = "新标题"
        task.status = TaskStatus.MATCHING
        task_repo.save(task)

        found = task_repo.find_by_id(task.task_id)
        assert found.title == "新标题"
        assert found.status == TaskStatus.MATCHING

    def test_find_by_demander(self, task_repo):
        t1 = StandardTask(demander_id="user-A", domain_tag=DomainTag.of("ride_hailing"))
        t2 = CustomTask(demander_id="user-A", domain_tag=DomainTag.of("group_buying"))
        t3 = StandardTask(demander_id="user-B", domain_tag=DomainTag.of("ride_hailing"))
        for t in [t1, t2, t3]:
            task_repo.save(t)

        results = task_repo.find_by_demander("user-A")
        assert len(results) == 2
        assert all(t.demander_id == "user-A" for t in results)

    def test_find_by_status_without_domain(self, task_repo):
        t1 = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride_hailing"))
        t2 = StandardTask(demander_id="u2", domain_tag=DomainTag.of("group_buying"))
        for t in [t1, t2]:
            task_repo.save(t)

        results = task_repo.find_by_status(TaskStatus.DRAFT)
        assert len(results) >= 2

    def test_find_by_status_with_domain_filter(self, task_repo):
        t1 = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride_hailing"))
        t2 = StandardTask(demander_id="u2", domain_tag=DomainTag.of("group_buying"))
        for t in [t1, t2]:
            task_repo.save(t)

        results = task_repo.find_by_status(
            TaskStatus.DRAFT, DomainTag.of("ride_hailing")
        )
        assert len(results) == 1
        assert results[0].domain_tag.value == "ride_hailing"

    def test_update_status(self, task_repo):
        task = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride_hailing"))
        task_repo.save(task)

        task_repo.update_status(task.task_id, TaskStatus.MATCHING)

        found = task_repo.find_by_id(task.task_id)
        assert found.status == TaskStatus.MATCHING

    def test_update_status_nonexistent_raises(self, task_repo):
        with pytest.raises(KeyError):
            task_repo.update_status("nonexistent", "completed")
```

- [ ] 运行测试验证失败

运行：`pytest tests/test_postgres_repos.py::TestPostgresTaskRepository -v`
预期：FAIL（ImportError: 无法导入 PostgresTaskRepository）

### 步骤 2.2：实现 PostgresTaskRepository

- [ ] 创建 `src/umcp_core/repositories/postgres/task_repo.py`

```python
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
```

### 步骤 2.3：创建 conftest.py 的 PG fixtures

- [ ] 创建 `tests/conftest.py`

```python
"""pytest 全局 fixture。

PG 测试需要 PostgreSQL 服务：
    docker compose up -d postgres
    export TEST_DATABASE_URL=postgresql://umcp:umcp@localhost:5432/umcp_dev
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# PG 测试标记
def pytest_configure(config):
    config.addinivalue_line("markers", "postgres: 需要 PostgreSQL 服务的测试")


# 无 PG 服务时跳过 PG 测试
PG_TEST_DSN = os.getenv(
    "TEST_DATABASE_URL", "postgresql://umcp:umcp@localhost:5432/umcp_dev"
)


def _pg_available() -> bool:
    try:
        from umcp_core.repositories.postgres.models import Base
        engine = create_engine(PG_TEST_DSN, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        Base.metadata.create_all(engine)
        engine.dispose()
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


def pytest_collection_modifyitems(config, items):
    """无 PG 服务时自动跳过标记为 postgres 的测试。"""
    if PG_AVAILABLE:
        return
    skip_pg = pytest.mark.skip(reason="PostgreSQL 不可用，设置 TEST_DATABASE_URL 并启动服务")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip_pg)


@pytest.fixture(scope="session")
def pg_engine():
    """会话级 PostgreSQL 引擎。"""
    from umcp_core.repositories.postgres.models import Base

    engine = create_engine(PG_TEST_DSN, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_bundle(pg_engine):
    """函数级仓储套件，测试后清空数据。"""
    from umcp_core.repositories.postgres.bundle import PostgresRepositoryBundle
    from umcp_core.repositories.postgres.models import Base

    bundle = PostgresRepositoryBundle(PG_TEST_DSN)
    yield bundle
    # 清空所有表（保证测试隔离）
    with bundle.engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE"))
        conn.commit()
    bundle.dispose()
```

### 步骤 2.4：创建 PostgresRepositoryBundle（最小实现，便于测试）

- [ ] 创建 `src/umcp_core/repositories/postgres/bundle.py`

```python
"""PostgreSQL 仓储套件。"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from umcp_core.repositories.postgres.models import Base
from umcp_core.repositories.postgres.task_repo import PostgresTaskRepository


class PostgresRepositoryBundle:
    """PostgreSQL 仓储套件，提供 6 个仓储 + 事件仓储。

    用法：
        bundle = PostgresRepositoryBundle("postgresql://...")
        server.use_postgres_repositories("postgresql://...")
    """

    def __init__(self, dsn: str, echo: bool = False) -> None:
        self.engine = create_engine(
            dsn,
            echo=echo,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_timeout=30,
        )
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

        # 仓储实例（逐步填充，本任务只填充 task_repo）
        self.task_repo = PostgresTaskRepository(self.SessionFactory)
        self.resource_repo = None  # 任务 3 填充
        self.deal_repo = None      # 任务 4 填充
        self.user_repo = None      # 任务 4 填充
        self.trust_repo = None     # 任务 5 填充
        self.event_repo = None     # 任务 6 填充

    @contextmanager
    def transaction(self) -> Session:
        """跨仓储的事务上下文。"""
        session = self.SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
```

- [ ] 运行测试验证通过

运行：`pytest tests/test_postgres_repos.py::TestPostgresTaskRepository -v`
预期：PASS（8 个测试，需要 PG 服务）

- [ ] Commit

```bash
git add src/umcp_core/repositories/postgres/task_repo.py src/umcp_core/repositories/postgres/bundle.py tests/test_postgres_repos.py tests/conftest.py
git commit -m "feat(postgres): PostgresTaskRepository + 测试 fixtures"
```

---

## 任务 3：PostgresResourceRepository

**文件：**
- 创建：`src/umcp_core/repositories/postgres/resource_repo.py`
- 修改：`src/umcp_core/repositories/postgres/bundle.py`
- 测试：`tests/test_postgres_repos.py`（追加 ResourceRepository 部分）

### 步骤 3.1：编写失败测试

- [ ] 在 `tests/test_postgres_repos.py` 末尾追加

```python
from umcp_core.core.resource import Resource, ResourceStatus, Capability


class _TestResource(Resource):
    """测试用 Resource 子类。"""

    def resource_type(self) -> str:
        return "test_resource"


@pytest.fixture
def resource_repo(pg_bundle):
    return pg_bundle.resource_repo


class TestPostgresResourceRepository:
    def test_save_and_find_by_id(self, resource_repo):
        cap = Capability(type="certification", name="business_license", verified=True)
        res = _TestResource(
            supplier_id="sup-1",
            domain_tag=DomainTag.of("ride_hailing"),
            capabilities=[cap],
            metadata={"location": "北京"},
        )
        resource_repo.save(res)

        found = resource_repo.find_by_id(res.resource_id)
        assert found is not None
        assert found.supplier_id == "sup-1"
        assert found.domain_tag.value == "ride_hailing"
        assert len(found.capabilities) == 1
        assert found.capabilities[0].name == "business_license"
        assert found.capabilities[0].verified is True
        assert found.metadata == {"location": "北京"}

    def test_find_by_id_nonexistent(self, resource_repo):
        assert resource_repo.find_by_id("nonexistent") is None

    def test_find_by_supplier(self, resource_repo):
        r1 = _TestResource(supplier_id="sup-A", domain_tag=DomainTag.of("ride_hailing"))
        r2 = _TestResource(supplier_id="sup-B", domain_tag=DomainTag.of("ride_hailing"))
        for r in [r1, r2]:
            resource_repo.save(r)

        results = resource_repo.find_by_supplier("sup-A")
        assert len(results) == 1
        assert results[0].supplier_id == "sup-A"

    def test_find_available_by_domain(self, resource_repo):
        r1 = _TestResource(supplier_id="sup-1", domain_tag=DomainTag.of("ride_hailing"))
        r1.status = ResourceStatus.IDLE
        r2 = _TestResource(supplier_id="sup-2", domain_tag=DomainTag.of("group_buying"))
        r2.status = ResourceStatus.IDLE
        for r in [r1, r2]:
            resource_repo.save(r)

        results = resource_repo.find_available(DomainTag.of("ride_hailing"))
        assert len(results) == 1
        assert results[0].domain_tag.value == "ride_hailing"

    def test_update_status(self, resource_repo):
        res = _TestResource(supplier_id="sup-1", domain_tag=DomainTag.of("ride_hailing"))
        resource_repo.save(res)

        resource_repo.update_status(res.resource_id, ResourceStatus.BUSY)

        found = resource_repo.find_by_id(res.resource_id)
        assert found.status == ResourceStatus.BUSY

    def test_update_status_nonexistent_raises(self, resource_repo):
        with pytest.raises(KeyError):
            resource_repo.update_status("nonexistent", "idle")
```

- [ ] 运行验证失败

运行：`pytest tests/test_postgres_repos.py::TestPostgresResourceRepository -v`
预期：FAIL（resource_repo 为 None）

### 步骤 3.2：实现 PostgresResourceRepository

- [ ] 创建 `src/umcp_core/repositories/postgres/resource_repo.py`

```python
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
```

- [ ] 修改 `src/umcp_core/repositories/postgres/bundle.py`，填充 resource_repo

```python
# 在 __init__ 中替换：
self.resource_repo = None  # 任务 3 填充
# 为：
from umcp_core.repositories.postgres.resource_repo import PostgresResourceRepository
self.resource_repo = PostgresResourceRepository(self.SessionFactory)
```

- [ ] 运行验证通过

运行：`pytest tests/test_postgres_repos.py::TestPostgresResourceRepository -v`
预期：PASS（6 个测试）

- [ ] Commit

```bash
git add src/umcp_core/repositories/postgres/resource_repo.py src/umcp_core/repositories/postgres/bundle.py tests/test_postgres_repos.py
git commit -m "feat(postgres): PostgresResourceRepository"
```

---

## 任务 4：PostgresDealRepository + PostgresUserRepository

**文件：**
- 创建：`src/umcp_core/repositories/postgres/deal_repo.py`
- 创建：`src/umcp_core/repositories/postgres/user_repo.py`
- 修改：`src/umcp_core/repositories/postgres/bundle.py`
- 测试：`tests/test_postgres_repos.py`（追加 Deal + User 部分）

### 步骤 4.1：编写失败测试

- [ ] 在 `tests/test_postgres_repos.py` 末尾追加

```python
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.base import User, Demander, PermissionSet, Supplier


class _TestUser(User):
    """测试用 User 子类。"""

    def __init__(self, user_id, name, metadata=None):
        super().__init__(user_id=user_id, name=name, metadata=metadata)

    def authenticate(self, credential) -> bool:
        return True


class _TestDemander(Demander):
    @property
    def permissions(self) -> PermissionSet:
        return PermissionSet({"create_task"})


@pytest.fixture
def deal_repo(pg_bundle):
    return pg_bundle.deal_repo


@pytest.fixture
def user_repo(pg_bundle):
    return pg_bundle.user_repo


class TestPostgresDealRepository:
    def test_save_and_find_by_id(self, deal_repo):
        deal = Deal(
            task_id="task-1",
            resource_id="res-1",
            demander_id="user-1",
            supplier_id="sup-1",
            final_amount=88.88,
        )
        deal_repo.save(deal)

        found = deal_repo.find_by_id(deal.deal_id)
        assert found is not None
        assert found.task_id == "task-1"
        assert found.final_amount == 88.88
        assert found.status == DealStatus.PENDING

    def test_find_by_task(self, deal_repo):
        d1 = Deal(task_id="task-A", resource_id="r1", demander_id="u1", supplier_id="s1")
        d2 = Deal(task_id="task-A", resource_id="r2", demander_id="u1", supplier_id="s2")
        d3 = Deal(task_id="task-B", resource_id="r3", demander_id="u2", supplier_id="s3")
        for d in [d1, d2, d3]:
            deal_repo.save(d)

        results = deal_repo.find_by_task("task-A")
        assert len(results) == 2

    def test_find_by_supplier(self, deal_repo):
        d1 = Deal(task_id="t1", resource_id="r1", demander_id="u1", supplier_id="sup-A")
        d2 = Deal(task_id="t2", resource_id="r2", demander_id="u2", supplier_id="sup-B")
        for d in [d1, d2]:
            deal_repo.save(d)

        results = deal_repo.find_by_supplier("sup-A")
        assert len(results) == 1


class TestPostgresUserRepository:
    def test_save_and_find_by_id(self, user_repo):
        user = _TestUser(user_id="u-1", name="张三")
        user.add_role(_TestDemander())
        user_repo.save(user)

        found = user_repo.find_by_id("u-1")
        assert found is not None
        assert found.name == "张三"
        assert "demander" in found.roles

    def test_find_by_name(self, user_repo):
        user = _TestUser(user_id="u-1", name="李四")
        user_repo.save(user)

        found = user_repo.find_by_name("李四")
        assert found is not None
        assert found.user_id == "u-1"

    def test_find_by_id_nonexistent(self, user_repo):
        assert user_repo.find_by_id("nonexistent") is None
```

- [ ] 运行验证失败

运行：`pytest tests/test_postgres_repos.py::TestPostgresDealRepository tests/test_postgres_repos.py::TestPostgresUserRepository -v`
预期：FAIL（deal_repo/user_repo 为 None）

### 步骤 4.2：实现 PostgresDealRepository

- [ ] 创建 `src/umcp_core/repositories/postgres/deal_repo.py`

```python
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
```

### 步骤 4.3：实现 PostgresUserRepository

- [ ] 创建 `src/umcp_core/repositories/postgres/user_repo.py`

```python
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
```

- [ ] 修改 `src/umcp_core/repositories/postgres/bundle.py`，填充 deal_repo 和 user_repo

```python
# 在 __init__ 中替换：
self.deal_repo = None      # 任务 4 填充
self.user_repo = None      # 任务 4 填充
# 为：
from umcp_core.repositories.postgres.deal_repo import PostgresDealRepository
from umcp_core.repositories.postgres.user_repo import PostgresUserRepository
self.deal_repo = PostgresDealRepository(self.SessionFactory)
self.user_repo = PostgresUserRepository(self.SessionFactory)
```

- [ ] 运行验证通过

运行：`pytest tests/test_postgres_repos.py::TestPostgresDealRepository tests/test_postgres_repos.py::TestPostgresUserRepository -v`
预期：PASS（6 个测试）

- [ ] Commit

```bash
git add src/umcp_core/repositories/postgres/deal_repo.py src/umcp_core/repositories/postgres/user_repo.py src/umcp_core/repositories/postgres/bundle.py tests/test_postgres_repos.py
git commit -m "feat(postgres): PostgresDealRepository + PostgresUserRepository"
```

---

## 任务 5：PostgresTrustRepository（含 domain 隔离）+ InMemory 同步

**文件：**
- 修改：`src/umcp_core/repositories/interfaces.py`
- 修改：`src/umcp_core/repositories/in_memory.py`
- 创建：`src/umcp_core/repositories/postgres/trust_repo.py`
- 修改：`src/umcp_core/repositories/postgres/bundle.py`
- 测试：`tests/test_postgres_repos.py`（追加 Trust 部分）

### 步骤 5.1：扩展 TrustRepository 接口

- [ ] 修改 `src/umcp_core/repositories/interfaces.py`，在 TrustRepository 类末尾追加

```python
class TrustRepository(ABC):
    """信任数据仓储接口。"""

    @abstractmethod
    def save_profile(self, profile: TrustProfile) -> TrustProfile:
        ...

    @abstractmethod
    def find_profile(self, user_id: str) -> TrustProfile | None:
        ...

    @abstractmethod
    def save_evaluation(self, evaluation: Evaluation) -> None:
        ...

    @abstractmethod
    def find_evaluations(self, user_id: str) -> list[Evaluation]:
        ...

    @abstractmethod
    def find_profile_by_domain(
        self, user_id: str, domain_tag: str
    ) -> TrustProfile | None:
        """按 domain 查询信任档案（domain 隔离）。"""
        ...
```

### 步骤 5.2：InMemory 同步实现 find_profile_by_domain

- [ ] 修改 `src/umcp_core/repositories/in_memory.py` 的 InMemoryTrustRepository

```python
class InMemoryTrustRepository(TrustRepository):
    def __init__(self) -> None:
        # 改为按 (user_id, domain_tag) 索引
        self._profiles: dict[tuple[str, str], TrustProfile] = {}
        self._evaluations: dict[str, list[Evaluation]] = {}
        self._lock = threading.RLock()

    def save_profile(self, profile: TrustProfile) -> TrustProfile:
        with self._lock:
            key = (profile.user_id, profile.domain_tag)
            self._profiles[key] = profile
            return profile

    def find_profile(self, user_id: str) -> TrustProfile | None:
        """返回该用户的任意一个 domain 的 profile（向后兼容）。"""
        with self._lock:
            for (uid, _domain), profile in self._profiles.items():
                if uid == user_id:
                    return profile
            return None

    def find_profile_by_domain(
        self, user_id: str, domain_tag: str
    ) -> TrustProfile | None:
        with self._lock:
            return self._profiles.get((user_id, domain_tag))

    def save_evaluation(self, evaluation: Evaluation) -> None:
        with self._lock:
            self._evaluations.setdefault(evaluation.evaluatee_id, []).append(evaluation)

    def find_evaluations(self, user_id: str) -> list[Evaluation]:
        with self._lock:
            return list(self._evaluations.get(user_id, []))
```

- [ ] 运行现有测试验证零回归

运行：`pytest tests/ --ignore=tests/test_postgres_repos.py --ignore=tests/test_recovery.py --ignore=tests/test_persistence_e2e.py -x -q`
预期：PASS（现有测试不应因接口扩展失败；如果有失败，需修复调用方）

### 步骤 5.3：编写 TrustRepository 失败测试

- [ ] 在 `tests/test_postgres_repos.py` 末尾追加

```python
from umcp_core.layers.l5 import TrustProfile, Evaluation


@pytest.fixture
def trust_repo(pg_bundle):
    return pg_bundle.trust_repo


class TestPostgresTrustRepository:
    def test_save_and_find_by_domain(self, trust_repo):
        profile = TrustProfile(
            user_id="user-1",
            dimension_scores={"delivery": 0.9, "quality": 0.8},
            overall_score=0.85,
            domain_tag="ride_hailing",
        )
        trust_repo.save_profile(profile)

        found = trust_repo.find_profile_by_domain("user-1", "ride_hailing")
        assert found is not None
        assert found.user_id == "user-1"
        assert found.domain_tag == "ride_hailing"
        assert found.overall_score == 0.85
        assert found.dimension_scores == {"delivery": 0.9, "quality": 0.8}

    def test_domain_isolation(self, trust_repo):
        """同一用户不同 domain 的信任档案应隔离存储。"""
        profile_ride = TrustProfile(
            user_id="user-1",
            overall_score=0.85,
            domain_tag="ride_hailing",
        )
        profile_buy = TrustProfile(
            user_id="user-1",
            overall_score=0.60,
            domain_tag="group_buying",
        )
        trust_repo.save_profile(profile_ride)
        trust_repo.save_profile(profile_buy)

        found_ride = trust_repo.find_profile_by_domain("user-1", "ride_hailing")
        found_buy = trust_repo.find_profile_by_domain("user-1", "group_buying")
        assert found_ride.overall_score == 0.85
        assert found_buy.overall_score == 0.60

    def test_find_by_domain_nonexistent(self, trust_repo):
        assert trust_repo.find_profile_by_domain("nobody", "ride_hailing") is None

    def test_find_profile_returns_any(self, trust_repo):
        """find_profile 向后兼容：返回任意 domain 的 profile。"""
        profile = TrustProfile(
            user_id="user-1",
            overall_score=0.7,
            domain_tag="ride_hailing",
        )
        trust_repo.save_profile(profile)

        found = trust_repo.find_profile("user-1")
        assert found is not None
        assert found.user_id == "user-1"

    def test_save_and_find_evaluations(self, trust_repo):
        eval1 = Evaluation(
            evaluator_id="u1",
            evaluatee_id="u2",
            task_id="t1",
            ratings={"quality": 0.9},
            domain_tag="ride_hailing",
        )
        trust_repo.save_evaluation(eval1)

        results = trust_repo.find_evaluations("u2")
        assert len(results) == 1
        assert results[0].ratings == {"quality": 0.9}
        assert results[0].domain_tag == "ride_hailing"

    def test_find_evaluations_empty(self, trust_repo):
        assert trust_repo.find_evaluations("nobody") == []
```

- [ ] 运行验证失败

运行：`pytest tests/test_postgres_repos.py::TestPostgresTrustRepository -v`
预期：FAIL（trust_repo 为 None）

### 步骤 5.4：实现 PostgresTrustRepository

- [ ] 创建 `src/umcp_core/repositories/postgres/trust_repo.py`

```python
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
```

- [ ] 修改 `src/umcp_core/repositories/postgres/bundle.py`，填充 trust_repo

```python
# 在 __init__ 中替换：
self.trust_repo = None     # 任务 5 填充
# 为：
from umcp_core.repositories.postgres.trust_repo import PostgresTrustRepository
self.trust_repo = PostgresTrustRepository(self.SessionFactory)
```

- [ ] 运行验证通过

运行：`pytest tests/test_postgres_repos.py::TestPostgresTrustRepository -v`
预期：PASS（6 个测试）

- [ ] 运行全量测试验证零回归

运行：`pytest tests/ --ignore=tests/test_recovery.py --ignore=tests/test_persistence_e2e.py -x -q`
预期：PASS（现有测试 + PG 仓储测试全通过）

- [ ] Commit

```bash
git add src/umcp_core/repositories/interfaces.py src/umcp_core/repositories/in_memory.py src/umcp_core/repositories/postgres/trust_repo.py src/umcp_core/repositories/postgres/bundle.py tests/test_postgres_repos.py
git commit -m "feat(postgres): PostgresTrustRepository + domain 隔离 + 接口扩展"
```

---

## 任务 6：PostgresEventRepository（含 replay）

**文件：**
- 创建：`src/umcp_core/repositories/postgres/event_repo.py`
- 修改：`src/umcp_core/repositories/postgres/bundle.py`
- 测试：`tests/test_postgres_repos.py`（追加 Event 部分）

### 步骤 6.1：编写失败测试

- [ ] 在 `tests/test_postgres_repos.py` 末尾追加

```python
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType


@pytest.fixture
def event_repo(pg_bundle):
    return pg_bundle.event_repo


class TestPostgresEventRepository:
    def test_append_and_replay_all(self, event_repo):
        e1 = Event(
            type=EventType.TASK_PUBLISHED,
            source_layer="L2",
            payload={"task_id": "task-1"},
        )
        e2 = Event(
            type=EventType.TASK_COMPLETED,
            source_layer="L2",
            payload={"task_id": "task-1"},
        )
        event_repo.append(e1)
        event_repo.append(e2)

        events = event_repo.replay()
        assert len(events) >= 2
        types = [e.type for e in events[-2:]]
        assert EventType.TASK_PUBLISHED in types
        assert EventType.TASK_COMPLETED in types

    def test_replay_by_aggregate_id(self, event_repo):
        e1 = Event(
            type=EventType.TASK_PUBLISHED,
            source_layer="L2",
            payload={"task_id": "task-A"},
        )
        e2 = Event(
            type=EventType.TASK_PUBLISHED,
            source_layer="L2",
            payload={"task_id": "task-B"},
        )
        event_repo.append(e1)
        event_repo.append(e2)

        events = event_repo.replay("task-A")
        assert len(events) == 1
        assert events[0].payload["task_id"] == "task-A"

    def test_replay_empty(self, event_repo):
        events = event_repo.replay()
        assert events == []

    def test_replay_preserves_payload(self, event_repo):
        e = Event(
            type=EventType.TASK_ASSIGNED,
            source_layer="L2",
            payload={"task_id": "t1", "resource_id": "r1", "extra": "data"},
        )
        event_repo.append(e)

        events = event_repo.replay("t1")
        assert len(events) == 1
        assert events[0].payload["resource_id"] == "r1"
        assert events[0].payload["extra"] == "data"
```

- [ ] 运行验证失败

运行：`pytest tests/test_postgres_repos.py::TestPostgresEventRepository -v`
预期：FAIL（event_repo 为 None）

### 步骤 6.2：实现 PostgresEventRepository

- [ ] 创建 `src/umcp_core/repositories/postgres/event_repo.py`

```python
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
```

- [ ] 修改 `src/umcp_core/repositories/postgres/bundle.py`，填充 event_repo

```python
# 在 __init__ 中替换：
self.event_repo = None     # 任务 6 填充
# 为：
from umcp_core.repositories.postgres.event_repo import PostgresEventRepository
self.event_repo = PostgresEventRepository(self.SessionFactory)
```

- [ ] 运行验证通过

运行：`pytest tests/test_postgres_repos.py::TestPostgresEventRepository -v`
预期：PASS（4 个测试）

- [ ] Commit

```bash
git add src/umcp_core/repositories/postgres/event_repo.py src/umcp_core/repositories/postgres/bundle.py tests/test_postgres_repos.py
git commit -m "feat(postgres): PostgresEventRepository + replay 回放"
```

---

## 任务 7：UMCPServer 集成（use_postgres_repositories + dispose）

**文件：**
- 修改：`src/umcp_core/server.py`
- 修改：`src/umcp_core/repositories/postgres/__init__.py`
- 测试：`tests/test_postgres_repos.py`（追加 Bundle 集成测试）

### 步骤 7.1：编写 Bundle 集成测试

- [ ] 在 `tests/test_postgres_repos.py` 末尾追加

```python
class TestPostgresRepositoryBundle:
    def test_bundle_provides_all_repos(self, pg_bundle):
        """Bundle 应提供 6 个仓储 + event_repo。"""
        assert pg_bundle.task_repo is not None
        assert pg_bundle.resource_repo is not None
        assert pg_bundle.deal_repo is not None
        assert pg_bundle.user_repo is not None
        assert pg_bundle.trust_repo is not None
        assert pg_bundle.event_repo is not None

    def test_bundle_transaction_context(self, pg_bundle):
        """transaction() 上下文应支持跨仓储原子操作。"""
        from umcp_core.repositories.postgres.models import TaskModel

        task = StandardTask(
            demander_id="user-tx",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        with pg_bundle.transaction() as session:
            session.merge(task_to_orm(task))

        found = pg_bundle.task_repo.find_by_id(task.task_id)
        assert found is not None
        assert found.demander_id == "user-tx"

    def test_bundle_transaction_rollback(self, pg_bundle):
        """transaction() 抛异常时应回滚。"""
        from umcp_core.repositories.postgres.models import TaskModel

        task = StandardTask(
            demander_id="user-rollback",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        with pytest.raises(ValueError):
            with pg_bundle.transaction() as session:
                session.merge(task_to_orm(task))
                raise ValueError("模拟失败")

        found = pg_bundle.task_repo.find_by_id(task.task_id)
        assert found is None
```

注：上述测试中 `task_to_orm` 需要导入：

```python
from umcp_core.repositories.postgres.converters import task_to_orm
```

加在文件顶部的 import 区域。

- [ ] 运行验证通过

运行：`pytest tests/test_postgres_repos.py::TestPostgresRepositoryBundle -v`
预期：PASS（3 个测试）

### 步骤 7.2：UMCPServer 集成

- [ ] 修改 `src/umcp_core/server.py`

在文件顶部 import 区追加（在现有 import 之后）：

```python
from umcp_core.repositories.postgres.bundle import PostgresRepositoryBundle
```

在 UMCPServer 类中，找到 `def use_in_memory_repositories` 方法之前，追加新方法：

```python
    def use_postgres_repositories(
        self, dsn: str, echo: bool = False
    ) -> PostgresRepositoryBundle:
        """使用 PostgreSQL 仓储（生产环境）。

        Args:
            dsn: PostgreSQL 连接字符串
            echo: 是否打印 SQL（调试用）

        Returns:
            PostgresRepositoryBundle 实例，可用于 dispose 或直接访问仓储
        """
        bundle = PostgresRepositoryBundle(dsn, echo)
        self.task_repo = bundle.task_repo
        self.resource_repo = bundle.resource_repo
        self.deal_repo = bundle.deal_repo
        self.user_repo = bundle.user_repo
        self.trust_repo = bundle.trust_repo
        self.event_repo = bundle.event_repo
        self.event_bus.subscribe_all(self.event_repo.append)
        self._postgres_bundle = bundle
        return bundle

    def dispose(self) -> None:
        """释放资源（关闭 DB 连接池）。"""
        if hasattr(self, "_postgres_bundle"):
            self._postgres_bundle.dispose()
            delattr(self, "_postgres_bundle")
```

- [ ] 修改 `src/umcp_core/repositories/postgres/__init__.py`

```python
"""PostgreSQL 仓储子包。"""

from umcp_core.repositories.postgres.bundle import PostgresRepositoryBundle
from umcp_core.repositories.postgres.task_repo import PostgresTaskRepository
from umcp_core.repositories.postgres.resource_repo import PostgresResourceRepository
from umcp_core.repositories.postgres.deal_repo import PostgresDealRepository
from umcp_core.repositories.postgres.user_repo import PostgresUserRepository
from umcp_core.repositories.postgres.trust_repo import PostgresTrustRepository
from umcp_core.repositories.postgres.event_repo import PostgresEventRepository

__all__ = [
    "PostgresRepositoryBundle",
    "PostgresTaskRepository",
    "PostgresResourceRepository",
    "PostgresDealRepository",
    "PostgresUserRepository",
    "PostgresTrustRepository",
    "PostgresEventRepository",
]
```

- [ ] 编写 server 集成测试

在 `tests/test_postgres_repos.py` 末尾追加：

```python
class TestUMCPServerPostgresIntegration:
    def test_use_postgres_repositories(self, pg_bundle):
        """server.use_postgres_repositories 应注入所有仓储。"""
        from umcp_core.server import UMCPServer

        server = UMCPServer()
        # 直接注入预构建的 bundle（避免重复创建 engine）
        server.task_repo = pg_bundle.task_repo
        server.resource_repo = pg_bundle.resource_repo
        server.deal_repo = pg_bundle.deal_repo
        server.user_repo = pg_bundle.user_repo
        server.trust_repo = pg_bundle.trust_repo
        server.event_repo = pg_bundle.event_repo
        server._postgres_bundle = pg_bundle
        server.event_bus.subscribe_all(server.event_repo.append)

        # 验证仓储可用
        task = StandardTask(
            demander_id="server-test",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        server.task_repo.save(task)
        found = server.task_repo.find_by_id(task.task_id)
        assert found is not None
        assert found.demander_id == "server-test"

    def test_dispose(self, pg_bundle):
        """dispose 应释放连接池。"""
        from umcp_core.server import UMCPServer

        server = UMCPServer()
        server._postgres_bundle = pg_bundle
        server.dispose()
        assert not hasattr(server, "_postgres_bundle")
```

- [ ] 运行验证通过

运行：`pytest tests/test_postgres_repos.py -v`
预期：PASS（全部 PG 仓储测试）

- [ ] 运行全量测试验证零回归

运行：`pytest tests/ --ignore=tests/test_recovery.py --ignore=tests/test_persistence_e2e.py -x -q`
预期：PASS

- [ ] Commit

```bash
git add src/umcp_core/server.py src/umcp_core/repositories/postgres/__init__.py tests/test_postgres_repos.py
git commit -m "feat(server): use_postgres_repositories + dispose 集成"
```

---

## 任务 8：复合任务恢复 + 事务持久化

**文件：**
- 修改：`src/umcp_core/server.py`
- 测试：`tests/test_recovery.py`（新建）

### 步骤 8.1：编写恢复失败测试

- [ ] 创建 `tests/test_recovery.py`

```python
"""L3: 复合任务智能恢复测试。

模拟 server 重启后，从 PostgreSQL 恢复未终态复合任务。
"""

from __future__ import annotations

import pytest
from datetime import datetime

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer

pytestmark = pytest.mark.postgres


def _make_subtask(task_id: str, domain: str = "ride_hailing") -> StandardTask:
    task = StandardTask(
        demander_id="user-1",
        domain_tag=DomainTag.of(domain),
    )
    task.task_id = task_id
    return task


def _make_server_with_pg(pg_bundle) -> UMCPServer:
    """构造带 PG 仓储的 server（不复用 pg_bundle 的 event_bus）。"""
    server = UMCPServer()
    server.task_repo = pg_bundle.task_repo
    server.resource_repo = pg_bundle.resource_repo
    server.deal_repo = pg_bundle.deal_repo
    server.user_repo = pg_bundle.user_repo
    server.trust_repo = pg_bundle.trust_repo
    server.event_repo = pg_bundle.event_repo
    server._postgres_bundle = pg_bundle
    server.event_bus.subscribe_all(server.event_repo.append)
    return server


class TestRecoverCompositeTasks:
    def test_recover_draft_subtask(self, pg_bundle):
        """DRAFT 子任务应被重新派发。"""
        server = _make_server_with_pg(pg_bundle)
        # 注册一个同步执行器（立即完成子任务）
        server.register_subtask_executor("ride_hailing", lambda sub: sub.complete())

        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )
        # 持久化
        server.task_repo.save(composite)
        server.task_repo.save(sub_a)
        server.task_repo.save(sub_b)

        # 模拟 sub_a 已完成，sub_b 仍 DRAFT
        sub_a.status = TaskStatus.COMPLETED
        server.task_repo.save(sub_a)
        sub_b.status = TaskStatus.DRAFT
        composite.status = TaskStatus.MATCHING
        server.task_repo.save(sub_b)
        server.task_repo.save(composite)

        # 恢复
        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["redispatched"] == 1

        # sub_b 应被派发并完成
        recovered_b = server.task_repo.find_by_id(sub_b.task_id)
        assert recovered_b.status == TaskStatus.COMPLETED
        # 复合任务应完成
        recovered_c = server.task_repo.find_by_id(composite.task_id)
        assert recovered_c.status == TaskStatus.COMPLETED

    def test_recover_skips_terminal_composite(self, pg_bundle):
        """已终态的复合任务应跳过。"""
        server = _make_server_with_pg(pg_bundle)
        server.register_subtask_executor("ride_hailing", lambda sub: sub.complete())

        sub = _make_subtask("x")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub],
        )
        # 全部设为终态
        sub.status = TaskStatus.COMPLETED
        composite.status = TaskStatus.COMPLETED
        server.task_repo.save(composite)
        server.task_repo.save(sub)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 0

    def test_recover_marks_in_progress_as_timeout(self, pg_bundle):
        """IN_PROGRESS 子任务应标记 _pending_timeout。"""
        server = _make_server_with_pg(pg_bundle)

        sub = _make_subtask("p")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub],
        )
        sub.status = TaskStatus.IN_PROGRESS
        composite.status = TaskStatus.MATCHING
        server.task_repo.save(composite)
        server.task_repo.save(sub)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["marked_timeout"] == 1
        assert stats["redispatched"] == 0

        recovered = server.task_repo.find_by_id(sub.task_id)
        assert "_pending_timeout" in recovered.custom_fields

    def test_recover_returns_empty_when_no_composites(self, pg_bundle):
        """无复合任务时返回全 0 统计。"""
        server = _make_server_with_pg(pg_bundle)
        stats = server.recover_composite_tasks()
        assert stats == {"recovered": 0, "redispatched": 0, "marked_timeout": 0}

    def test_recover_multiple_composites(self, pg_bundle):
        """多个复合任务应串行恢复。"""
        server = _make_server_with_pg(pg_bundle)
        server.register_subtask_executor("ride_hailing", lambda sub: sub.complete())

        for i in range(3):
            sub = _make_subtask(f"multi-{i}")
            composite = CompositeTask(
                demander_id="user-1",
                domain_tag=DomainTag.of("ride_hailing"),
                subtasks=[sub],
            )
            server.task_repo.save(composite)
            server.task_repo.save(sub)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 3
        assert stats["redispatched"] == 3

    def test_recover_completes_when_all_subtasks_terminal(self, pg_bundle):
        """恢复后所有子任务终态时应完成父任务。"""
        server = _make_server_with_pg(pg_bundle)

        sub_a = _make_subtask("ca")
        sub_b = _make_subtask("cb")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )
        sub_a.status = TaskStatus.COMPLETED
        sub_b.status = TaskStatus.COMPLETED
        composite.status = TaskStatus.MATCHING
        server.task_repo.save(composite)
        server.task_repo.save(sub_a)
        server.task_repo.save(sub_b)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["redispatched"] == 0  # 都已终态，无需派发

        recovered = server.task_repo.find_by_id(composite.task_id)
        assert recovered.status == TaskStatus.COMPLETED
```

- [ ] 运行验证失败

运行：`pytest tests/test_recovery.py -v`
预期：FAIL（`recover_composite_tasks` 方法不存在）

### 步骤 8.2：实现恢复与事务持久化

- [ ] 修改 `src/umcp_core/server.py`

在文件顶部 import 区追加：

```python
from umcp_core.repositories.postgres.converters import task_to_orm
from umcp_core.repositories.postgres.models import CompositeDependencyModel
from umcp_core.repositories.postgres.task_repo import PostgresTaskRepository
from umcp_core.core.composite_task import CompositeTask
```

在 UMCPServer 类中，找到 `execute_composite` 方法，在方法开头（校验之后、绑定 EventBus 之前）插入持久化逻辑：

```python
    def execute_composite(self, composite: CompositeTask) -> None:
        """执行复合任务（编排入口）。"""
        # ... 现有校验逻辑不变 ...

        # 持久化父任务和子任务（原子事务）
        self._persist_composite_atomic(composite)

        # 绑定 EventBus
        composite.bind_event_bus(self.event_bus)

        # ... 后续逻辑不变（publish、_register_composite_bridge、_dispatch_ready_subtasks） ...
```

注意：如果 `execute_composite` 中已有 `self.task_repo.save(composite)` 和子任务 save，替换为 `self._persist_composite_atomic(composite)`。

在 UMCPServer 类末尾追加新方法：

```python
    def _persist_composite_atomic(self, composite: CompositeTask) -> None:
        """原子持久化复合任务及其子任务和依赖关系。"""
        if not hasattr(self, "_postgres_bundle"):
            # InMemory 路径，逐个 save
            self.task_repo.save(composite)
            for sub in composite.subtasks:
                self.task_repo.save(sub)
            return

        with self._postgres_bundle.transaction() as session:
            session.merge(task_to_orm(composite))
            for sub in composite.subtasks:
                session.merge(task_to_orm(sub))
            # 持久化依赖关系
            for sub_id, deps in composite.dependencies.items():
                for dep_id in deps:
                    session.merge(
                        CompositeDependencyModel(
                            composite_task_id=composite.task_id,
                            subtask_id=sub_id,
                            depends_on_id=dep_id,
                        )
                    )

    def recover_composite_tasks(self) -> dict[str, int]:
        """启动时智能恢复未终态的复合任务。

        Returns:
            统计 dict：{"recovered": N, "redispatched": M, "marked_timeout": K}
        """
        stats = {"recovered": 0, "redispatched": 0, "marked_timeout": 0}

        if self.task_repo is None:
            return stats

        # 1. 查询所有未终态的 CompositeTask
        non_terminal_statuses = [
            TaskStatus.DRAFT, TaskStatus.MATCHING,
            TaskStatus.PUBLISHED, TaskStatus.ASSIGNED,
            TaskStatus.IN_PROGRESS,
        ]
        composites: list[CompositeTask] = []
        for status in non_terminal_statuses:
            tasks = self.task_repo.find_by_status(status.value)
            composites.extend(
                t for t in tasks if t.task_type() == "composite"
            )

        for composite in composites:
            stats["recovered"] += 1
            self._recover_single_composite(composite, stats)

        return stats

    def _recover_single_composite(
        self, composite: CompositeTask, stats: dict[str, int]
    ) -> None:
        """恢复单个复合任务。"""
        # 重新绑定 EventBus
        composite.bind_event_bus(self.event_bus)

        # 重新注册 TASK_COMPLETED 桥接
        self._register_composite_bridge(composite)

        # 遍历子任务，按状态分类处理
        for subtask in composite.subtasks:
            if TaskStatus.is_terminal(subtask.status):
                continue

            if subtask.status == TaskStatus.DRAFT:
                self._execute_subtask_by_domain(subtask)
                stats["redispatched"] += 1
            elif subtask.status in (TaskStatus.MATCHING, TaskStatus.PUBLISHED):
                self._execute_subtask_by_domain(subtask)
                stats["redispatched"] += 1
            elif subtask.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
                # 标记待超时（阶段五 D 实现真正的超时取消）
                subtask.custom_fields["_pending_timeout"] = datetime.utcnow().isoformat()
                self.task_repo.save(subtask)
                stats["marked_timeout"] += 1

        # 检查是否所有子任务已终态
        if all(TaskStatus.is_terminal(s.status) for s in composite.subtasks):
            if any(s.status == TaskStatus.CANCELLED for s in composite.subtasks):
                # 有 CANCELLED → 父任务失败
                composite.status = TaskStatus.CANCELLED
                composite.updated_at = datetime.utcnow()
            else:
                # 全部 COMPLETED → 父任务完成
                composite.status = TaskStatus.COMPLETED
                composite.updated_at = datetime.utcnow()
            self.task_repo.save(composite)
```

注意：`_register_composite_bridge` 方法已在阶段四 C 实现中存在，如果不存在需要补充。检查 server.py 是否已有此方法：

```python
    def _register_composite_bridge(self, composite: CompositeTask) -> None:
        """为复合任务注册 TASK_COMPLETED → SUBTASK_* 桥接。"""
        subtask_ids = {s.task_id for s in composite.subtasks}

        def _bridge_to_subtask_event(event: Event) -> None:
            task_id = event.payload.get("task_id")
            if task_id not in subtask_ids:
                return
            subtask = composite.find_subtask(task_id)
            if subtask is None:
                return
            if event.payload.get("cancelled"):
                composite.emit_subtask_event(subtask, EventType.SUBTASK_CANCELLED)
            else:
                composite.emit_subtask_event(subtask, EventType.SUBTASK_COMPLETED)
            self._dispatch_ready_subtasks(composite)
            if TaskStatus.is_terminal(composite.status):
                self.event_bus.unsubscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)

        self.event_bus.subscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)
```

如果 server.py 已有此方法（阶段四 C 实现），则不需要重复添加。

- [ ] 修改 `start()` 方法，集成恢复

找到 `start()` 方法，在 `self._started = True` 之前插入：

```python
    def start(self) -> None:
        if self._started:
            print("[UMCPServer] 已在运行中", file=sys.stderr)
            return
        self._validate_required_components()

        # 持久化恢复：启动时扫描未终态复合任务
        if self.task_repo is not None:
            stats = self.recover_composite_tasks()
            if stats["recovered"] > 0:
                import sys
                print(
                    f"[UMCPServer] 恢复 {stats['recovered']} 个复合任务"
                    f"（重新派发 {stats['redispatched']}，标记待超时 {stats['marked_timeout']}）",
                    file=sys.stderr,
                )

        print(
            f"[UMCPServer] 协议栈已启动。已加载插件: "
            f"{[p.name for p in self._plugins] or '<无>'}"
        )
        self._started = True
```

- [ ] 运行验证通过

运行：`pytest tests/test_recovery.py -v`
预期：PASS（6 个测试）

- [ ] Commit

```bash
git add src/umcp_core/server.py tests/test_recovery.py
git commit -m "feat(server): 复合任务智能恢复 + 事务持久化"
```

---

## 任务 9：Alembic 迁移

**文件：**
- 创建：`migrations/alembic.ini`
- 创建：`migrations/env.py`
- 创建：`migrations/script.py.mako`
- 创建：`migrations/versions/001_init_schema.py`

### 步骤 9.1：创建 Alembic 配置

- [ ] 创建 `migrations/alembic.ini`

```ini
[alembic]
script_location = migrations
sqlalchemy.url = postgresql://umcp:umcp@localhost:5432/umcp_dev

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] 创建 `migrations/env.py`

```python
"""Alembic 迁移环境。"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 导入 Base.metadata 作为 target_metadata
from umcp_core.repositories.postgres.models import Base

config = context.config

# 从环境变量覆盖 DB URL
db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] 创建 `migrations/script.py.mako`

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

### 步骤 9.2：创建初始 schema 迁移

- [ ] 创建 `migrations/versions/001_init_schema.py`

```python
"""初始 schema：7 张表 + 索引

Revision ID: 001
Revises:
Create Date: 2026-07-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tasks
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("demander_id", sa.String(64), nullable=False),
        sa.Column("domain_tag", sa.String(32), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=True),
        sa.Column("assigned_resource_id", sa.String(64), nullable=True),
        sa.Column("parent_task_id", sa.String(64), nullable=True),
        sa.Column("custom_fields", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_tasks_demander", "tasks", ["demander_id"])
    op.create_index("idx_tasks_status", "tasks", ["status", "domain_tag"])
    op.create_index("idx_tasks_parent", "tasks", ["parent_task_id"])

    # resources
    op.create_table(
        "resources",
        sa.Column("resource_id", sa.String(64), primary_key=True),
        sa.Column("supplier_id", sa.String(64), nullable=False),
        sa.Column("domain_tag", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_resources_supplier", "resources", ["supplier_id"])
    op.create_index("idx_resources_available", "resources", ["domain_tag", "status"])

    # deals
    op.create_table(
        "deals",
        sa.Column("deal_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=False),
        sa.Column("demander_id", sa.String(64), nullable=False),
        sa.Column("final_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_deals_task", "deals", ["task_id"])
    op.create_index("idx_deals_supplier", "deals", ["supplier_id"])

    # users
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("user_type", sa.String(32), nullable=False),
        sa.Column("roles", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # trust_profiles
    op.create_table(
        "trust_profiles",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("domain_tag", sa.String(32), primary_key=True),
        sa.Column("overall_score", sa.Numeric(4, 3), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
    )

    # trust_evaluations
    op.create_table(
        "trust_evaluations",
        sa.Column("evaluator_id", sa.String(64), primary_key=True),
        sa.Column("evaluatee_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("domain_tag", sa.String(32), nullable=False),
        sa.Column("ratings", postgresql.JSONB(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_evaluations_user", "trust_evaluations", ["evaluatee_id", "domain_tag"])

    # events
    op.create_table(
        "events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source_layer", sa.String(16), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("deal_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_events_task", "events", ["task_id"])
    op.create_index("idx_events_deal", "events", ["deal_id"])
    op.create_index("idx_events_user", "events", ["user_id"])
    op.create_index("idx_events_type_time", "events", ["event_type", "created_at"])

    # composite_dependencies
    op.create_table(
        "composite_dependencies",
        sa.Column("composite_task_id", sa.String(64), nullable=False),
        sa.Column("subtask_id", sa.String(64), primary_key=True),
        sa.Column("depends_on_id", sa.String(64), primary_key=True),
    )
    op.create_index("idx_deps_composite", "composite_dependencies", ["composite_task_id"])


def downgrade() -> None:
    op.drop_table("composite_dependencies")
    op.drop_table("events")
    op.drop_table("trust_evaluations")
    op.drop_table("trust_profiles")
    op.drop_table("users")
    op.drop_table("deals")
    op.drop_table("resources")
    op.drop_table("tasks")
```

- [ ] 验证迁移可用（需要 PG 服务）

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core ; $env:DATABASE_URL="postgresql://umcp:umcp@localhost:5432/umcp_dev" ; alembic upgrade head`
预期：成功创建 7 张表

- [ ] Commit

```bash
git add migrations/
git commit -m "feat(migrations): Alembic 初始 schema（7 张表 + 索引）"
```

---

## 任务 10：端到端测试 + Docker + 依赖

**文件：**
- 创建：`tests/test_persistence_e2e.py`
- 创建：`docker-compose.yml`
- 修改：`pyproject.toml`

### 步骤 10.1：编写端到端持久化测试

- [ ] 创建 `tests/test_persistence_e2e.py`

```python
"""L4: 端到端持久化测试。

验证完整的启动→执行→重启→恢复→继续流程。
"""

from __future__ import annotations

import pytest

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.server import UMCPServer

pytestmark = pytest.mark.postgres


def _make_server(pg_bundle) -> UMCPServer:
    """构造带 PG 仓储的 server。"""
    server = UMCPServer()
    server.task_repo = pg_bundle.task_repo
    server.resource_repo = pg_bundle.resource_repo
    server.deal_repo = pg_bundle.deal_repo
    server.user_repo = pg_bundle.user_repo
    server.trust_repo = pg_bundle.trust_repo
    server.event_repo = pg_bundle.event_repo
    server._postgres_bundle = pg_bundle
    server.event_bus.subscribe_all(server.event_repo.append)
    return server


class TestPersistenceE2E:
    def test_task_persists_across_restart(self, pg_bundle):
        """任务应在"重启"后仍可查询。"""
        # server 1：创建任务
        server1 = _make_server(pg_bundle)
        task = StandardTask(
            demander_id="user-e2e-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="持久化测试",
        )
        server1.task_repo.save(task)
        task_id = task.task_id

        # 模拟重启：新 server 实例（同一 PG）
        server2 = _make_server(pg_bundle)
        found = server2.task_repo.find_by_id(task_id)
        assert found is not None
        assert found.demander_id == "user-e2e-1"
        assert found.title == "持久化测试"

    def test_composite_recovers_and_continues(self, pg_bundle):
        """复合任务在"重启"后应恢复并继续执行。"""
        # server 1：创建复合任务，子任务未完成
        server1 = _make_server(pg_bundle)
        server1.register_subtask_executor("ride_hailing", lambda sub: sub.complete())

        sub_a = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        sub_a.task_id = "e2e-a"
        sub_b = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        sub_b.task_id = "e2e-b"
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )

        # 持久化（模拟中断前的状态）
        server1.task_repo.save(composite)
        server1.task_repo.save(sub_a)
        server1.task_repo.save(sub_b)

        # sub_a 已完成，sub_b 仍 DRAFT，composite 处于 MATCHING
        sub_a.status = TaskStatus.COMPLETED
        sub_b.status = TaskStatus.DRAFT
        composite.status = TaskStatus.MATCHING
        server1.task_repo.save(sub_a)
        server1.task_repo.save(sub_b)
        server1.task_repo.save(composite)

        # 模拟重启：新 server 实例
        server2 = _make_server(pg_bundle)
        server2.register_subtask_executor("ride_hailing", lambda sub: sub.complete())

        stats = server2.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["redispatched"] == 1

        # 验证最终状态
        recovered_composite = server2.task_repo.find_by_id(composite.task_id)
        assert recovered_composite.status == TaskStatus.COMPLETED
        recovered_b = server2.task_repo.find_by_id(sub_b.task_id)
        assert recovered_b.status == TaskStatus.COMPLETED

    def test_event_log_persists(self, pg_bundle):
        """事件日志应持久化并支持回放。"""
        from umcp_core.events.bus import Event
        from umcp_core.events.types import EventType

        server1 = _make_server(pg_bundle)
        server1.event_bus.publish(
            Event(
                type=EventType.TASK_PUBLISHED,
                source_layer="L2",
                payload={"task_id": "evt-task-1"},
            )
        )

        # 模拟重启
        server2 = _make_server(pg_bundle)
        events = server2.event_repo.replay("evt-task-1")
        assert len(events) >= 1
        assert events[0].payload["task_id"] == "evt-task-1"

    def test_transaction_atomicity(self, pg_bundle):
        """复合任务持久化应是原子的（失败回滚）。"""
        from umcp_core.repositories.postgres.models import TaskModel
        from umcp_core.repositories.postgres.converters import task_to_orm

        task = StandardTask(
            demander_id="user-tx-fail",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        task.task_id = "tx-fail-1"

        with pytest.raises(ValueError):
            with pg_bundle.transaction() as session:
                session.merge(task_to_orm(task))
                raise ValueError("模拟失败")

        # 验证未持久化
        found = pg_bundle.task_repo.find_by_id("tx-fail-1")
        assert found is None

    def test_in_memory_path_unaffected(self):
        """InMemory 路径应保持原行为（无 PG 依赖）。"""
        server = UMCPServer()
        server.use_in_memory_repositories()

        task = StandardTask(
            demander_id="user-mem",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        server.task_repo.save(task)

        found = server.task_repo.find_by_id(task.task_id)
        assert found is not None
        assert found.demander_id == "user-mem"
```

- [ ] 运行验证通过

运行：`pytest tests/test_persistence_e2e.py -v`
预期：PASS（5 个测试）

### 步骤 10.2：创建 docker-compose.yml

- [ ] 创建 `docker-compose.yml`（在项目根目录 `c:\trae_projects\tongyongjiaoyi\umcp-core\`）

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: umcp_postgres
    environment:
      POSTGRES_USER: umcp
      POSTGRES_PASSWORD: umcp
      POSTGRES_DB: umcp_dev
    ports:
      - "5432:5432"
    volumes:
      - umcp_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U umcp"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  umcp_pg_data:
```

### 步骤 10.3：更新 pyproject.toml 依赖

- [ ] 读取现有 `pyproject.toml`

运行：用 Read 工具读取 `c:\trae_projects\tongyongjiaoyi\umcp-core\pyproject.toml`

- [ ] 在 `[project.optional-dependencies]` 添加 postgres 依赖，并在 dev 依赖中追加

在 `pyproject.toml` 中找到 `[project.optional-dependencies]` 段（如果没有则创建），添加：

```toml
[project.optional-dependencies]
postgres = [
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg[binary]>=3.1.0",
]
```

如果已有 `dev` 可选依赖，在其中追加这三个包；如果没有，创建：

```toml
dev = [
    "pytest>=7.0.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg[binary]>=3.1.0",
]
```

- [ ] 安装新依赖

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core ; pip install -e ".[dev]"`
预期：成功安装 sqlalchemy、alembic、psycopg

- [ ] 运行全量测试验证

运行：`pytest tests/ -v --tb=short`
预期：全部 PASS（442 现有 + ≥48 新增 = ≥490 passed，PG 测试需要 PG 服务）

- [ ] Commit

```bash
git add tests/test_persistence_e2e.py docker-compose.yml pyproject.toml
git commit -m "feat: 端到端持久化测试 + Docker Compose + 依赖声明"
```

---

## 自检

### 1. 规格覆盖度

| 规格章节 | 对应任务 | 状态 |
|---------|---------|------|
| §1 架构概述 | 全部任务（文件结构匹配） | ✅ |
| §2 数据库 Schema | 任务 1（ORM 模型）+ 任务 9（迁移） | ✅ |
| §3 ORM 模型与转换器 | 任务 1 | ✅ |
| §4 仓储实现 | 任务 2-6 | ✅ |
| §5 复合任务智能恢复 | 任务 8 | ✅ |
| §6 事务保证与错误处理 | 任务 8（`_persist_composite_atomic`）+ 任务 6（事件持久化失败告警） | ✅ |
| §7 迁移管理与测试策略 | 任务 9（迁移）+ 任务 1-8,10（测试） | ✅ |
| §8 验收标准 | 全部任务完成后验证 | ✅ |

**遗漏：** 无。所有规格章节都有对应任务。

### 2. 占位符扫描

- ✅ 无"待定"/"TODO"/"后续实现"
- ✅ 无"添加适当的错误处理"等模糊描述
- ✅ 所有代码步骤都有完整代码块
- ✅ 无"类似任务 N"的重复引用

### 3. 类型一致性

- ✅ `PostgresTaskRepository` 在任务 2 定义，任务 7 的 `use_postgres_repositories` 引用一致
- ✅ `task_to_orm` / `task_from_orm` 在任务 1 定义，任务 2-8 引用一致
- ✅ `TrustProfile.domain_tag` 在任务 1.1 添加，任务 5 的转换器和仓储使用一致
- ✅ `find_profile_by_domain(user_id, domain_tag)` 签名在任务 5 的接口、InMemory、PG 实现中一致
- ✅ `recover_composite_tasks()` 返回 `dict[str, int]`，任务 8 实现与规格 §5.2 一致

### 4. 规格修订说明

计划中发现规格 §8.1 声明"`core/`/`events/`/`layers/` 零修改"，但任务 1.1 需要修改 `layers/l5/trust.py`（给 TrustProfile 和 Evaluation 加 domain_tag 字段）。这是必要的向后兼容扩展（默认空字符串），不破坏现有行为。规格 §8.1 应修订为：

> **核心库改动：** `server.py` 新增方法；`repositories/` 新增 `postgres/` 子包；`layers/l5/trust.py` 给 TrustProfile 和 Evaluation 加 `domain_tag` 字段（向后兼容扩展）；`repositories/interfaces.py` 的 TrustRepository 新增 `find_profile_by_domain` 方法；`repositories/in_memory.py` 同步实现；`core/`/`events/` 零修改。

---

## 执行交接

计划已完成并保存到 `docs/plans/2026-07-28-postgres-persistence.md`。两种执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**
