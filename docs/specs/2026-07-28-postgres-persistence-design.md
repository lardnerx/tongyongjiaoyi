# 阶段五 A：持久化与生产化 设计规格

> **状态：** 已批准（2026-07-28）
> **目标：** 将全内存协议栈改造为 PostgreSQL 持久化，支持重启恢复与复合任务智能恢复。
> **前置阶段：** 阶段四 C（复合任务编排）已完成，442 passed。

---

## 1. 架构概述

### 设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 数据库 | PostgreSQL 16 | 原生 JSONB 支持、成熟稳定、生产级 |
| ORM | SQLAlchemy 2.0 | 类型安全、DeclarativeBase 风格、社区主流 |
| 事件存储 | 混合模式（当前状态 + 事件日志） | 业务表存当前状态，events 表存完整事件日志用于审计 |
| 复合任务恢复 | 智能恢复 | 按子任务当前状态分类处理（DRAFT 重派/IN_PROGRESS 标记待超时） |
| 映射策略 | 双层架构（领域对象 + ORM 模型分离） | 领域对象零修改，ORM 模型可独立演进 |

### 架构图

```
┌─────────────────────────────────────────────────────┐
│                    UMCPServer                        │
│  use_postgres_repositories(dsn) → 注册 6 个仓储      │
│  recover_on_start() → 智能恢复未终态复合任务          │
├─────────────────────────────────────────────────────┤
│  仓储层（双层架构）                                   │
│  ┌───────────────────────────────────────────────┐  │
│  │ 领域对象（Task/Resource/Deal/User/...）        │  │
│  │  ↕ 转换器（to_orm / from_orm）                │  │
│  │ ORM 模型（TaskModel/ResourceModel/...）        │  │
│  │  ↕ SQLAlchemy 2.0 Session                     │  │
│  │ PostgreSQL                                    │  │
│  └───────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│  事件存储（混合模式）                                 │
│  event_bus.subscribe_all(event_repo.append)         │
│  → events 表（完整事件日志，用于审计/回放）           │
│  recover_on_start() 扫描未终态复合任务                │
│  → 检查子任务当前状态 → 重新派发就绪子任务             │
└─────────────────────────────────────────────────────┘
```

### 新增文件结构

```
src/umcp_core/repositories/postgres/       # 新增子包
  __init__.py
  models.py                                # SQLAlchemy ORM 模型（7 张表）
  converters.py                            # 领域对象 ↔ ORM 模型转换器
  task_repo.py                             # PostgresTaskRepository
  resource_repo.py                         # PostgresResourceRepository
  deal_repo.py                             # PostgresDealRepository
  user_repo.py                             # PostgresUserRepository
  trust_repo.py                            # PostgresTrustRepository
  event_repo.py                            # PostgresEventRepository
  bundle.py                                # PostgresRepositoryBundle
migrations/                                # 新增
  alembic.ini
  env.py
  versions/
    001_init_schema.py
    002_seed_domains.py
docker-compose.yml                         # 新增
tests/
  test_postgres_repos.py                   # 新增
  test_recovery.py                         # 新增
  conftest.py                              # 新增
```

### 关键设计原则

- 领域对象零修改（`Task`/`Resource` 等不依赖 SQLAlchemy）
- 仓储接口零修改（`TaskRepository` ABC 不变）
- 新增 `PostgresRepositoryBundle` 对标 `InMemoryRepositoryBundle`
- server.py 新增 `use_postgres_repositories(dsn)` 方法
- InMemory 路径保持原行为，开发调试仍可用

---

## 2. 数据库 Schema

### 2.1 tasks 表

```sql
CREATE TABLE tasks (
    task_id          VARCHAR(64) PRIMARY KEY,
    task_type        VARCHAR(32) NOT NULL,        -- standard/custom/package/composite
    demander_id      VARCHAR(64) NOT NULL,
    domain_tag       VARCHAR(32) NOT NULL,
    title            VARCHAR(256),
    description      TEXT,
    status           VARCHAR(32) NOT NULL,        -- draft/matching/published/assigned/in_progress/completed/cancelled
    supplier_id      VARCHAR(64),
    assigned_resource_id VARCHAR(64),
    parent_task_id   VARCHAR(64),                 -- 复合任务的子任务指向父任务
    custom_fields    JSONB,                       -- 灵活扩展字段
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL
);
CREATE INDEX idx_tasks_demander ON tasks(demander_id);
CREATE INDEX idx_tasks_status ON tasks(status, domain_tag);
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);
```

### 2.2 resources 表

```sql
CREATE TABLE resources (
    resource_id      VARCHAR(64) PRIMARY KEY,
    supplier_id      VARCHAR(64) NOT NULL,
    domain_tag       VARCHAR(32) NOT NULL,
    status           VARCHAR(32) NOT NULL,        -- idle/busy/offline
    capabilities     JSONB,                       -- [{name, verified}]
    metadata         JSONB,
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL
);
CREATE INDEX idx_resources_supplier ON resources(supplier_id);
CREATE INDEX idx_resources_available ON resources(domain_tag, status);
```

### 2.3 deals 表

```sql
CREATE TABLE deals (
    deal_id          VARCHAR(64) PRIMARY KEY,
    task_id          VARCHAR(64) NOT NULL,
    supplier_id      VARCHAR(64) NOT NULL,
    demander_id      VARCHAR(64) NOT NULL,
    final_amount     NUMERIC(12,2),
    status           VARCHAR(32) NOT NULL,        -- pending/in_progress/completed/disputed/cancelled
    outcome          VARCHAR(32),                 -- completed/refunded
    metadata         JSONB,
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL
);
CREATE INDEX idx_deals_task ON deals(task_id);
CREATE INDEX idx_deals_supplier ON deals(supplier_id);
```

### 2.4 users 表

```sql
CREATE TABLE users (
    user_id          VARCHAR(64) PRIMARY KEY,
    name             VARCHAR(128) NOT NULL,
    phone            VARCHAR(32) UNIQUE,
    user_type        VARCHAR(32) NOT NULL,        -- demander/supplier
    credentials      JSONB,                       -- PermissionSet 序列化
    metadata         JSONB,
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL
);
CREATE INDEX idx_users_phone ON users(phone);
```

### 2.5 trust_profiles + trust_evaluations 表

```sql
CREATE TABLE trust_profiles (
    user_id          VARCHAR(64) NOT NULL,
    domain_tag       VARCHAR(32) NOT NULL,
    overall_score    NUMERIC(4,3) NOT NULL,
    dimension_scores JSONB NOT NULL,              -- {delivery, quality, service, cost_performance}
    badges           JSONB,
    updated_at       TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, domain_tag)
);

CREATE TABLE trust_evaluations (
    evaluation_id    VARCHAR(64) PRIMARY KEY,
    user_id          VARCHAR(64) NOT NULL,
    domain_tag       VARCHAR(32) NOT NULL,
    deal_id          VARCHAR(64),
    dimensions       JSONB NOT NULL,
    overall          NUMERIC(4,3) NOT NULL,
    comment          TEXT,
    created_at       TIMESTAMP NOT NULL
);
CREATE INDEX idx_evaluations_user ON trust_evaluations(user_id, domain_tag);
```

### 2.6 events 表

```sql
CREATE TABLE events (
    event_id         BIGSERIAL PRIMARY KEY,
    event_type       VARCHAR(64) NOT NULL,
    source_layer     VARCHAR(16) NOT NULL,
    task_id          VARCHAR(64),
    deal_id          VARCHAR(64),
    user_id          VARCHAR(64),
    payload          JSONB NOT NULL,
    created_at       TIMESTAMP NOT NULL
);
CREATE INDEX idx_events_task ON events(task_id);
CREATE INDEX idx_events_deal ON events(deal_id);
CREATE INDEX idx_events_user ON events(user_id);
CREATE INDEX idx_events_type_time ON events(event_type, created_at);
```

### 2.7 composite_dependencies 表

```sql
CREATE TABLE composite_dependencies (
    composite_task_id VARCHAR(64) NOT NULL,
    subtask_id        VARCHAR(64) NOT NULL,
    depends_on_id     VARCHAR(64) NOT NULL,
    PRIMARY KEY (subtask_id, depends_on_id)
);
CREATE INDEX idx_deps_composite ON composite_dependencies(composite_task_id);
```

### 关键设计点

- `tasks.parent_task_id` 建立复合任务与子任务的层级关系
- `custom_fields`/`capabilities`/`metadata` 用 JSONB 存储灵活字段（PostgreSQL 原生支持）
- `trust_profiles` 用 `PRIMARY KEY (user_id, domain_tag)` 保证 domain 隔离
- `events` 表用 BIGSERIAL 自增主键，支持高吞吐事件写入
- 复合任务的 `dependencies` 独立表存储，便于查询 DAG 拓扑

---

## 3. ORM 模型与转换器

### 3.1 ORM 模型（`src/umcp_core/repositories/postgres/models.py`）

使用 SQLAlchemy 2.0 的 `DeclarativeBase` + `Mapped` 类型注解风格：

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

class Base(DeclarativeBase):
    pass

class TaskModel(Base):
    __tablename__ = "tasks"
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32))
    demander_id: Mapped[str] = mapped_column(String(64))
    domain_tag: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custom_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
```

其余 6 个模型（ResourceModel/DealModel/UserModel/TrustProfileModel/TrustEvaluationModel/EventModel/CompositeDependencyModel）按相同风格定义。

### 3.2 转换器（`src/umcp_core/repositories/postgres/converters.py`）

每个转换器是一对函数：`to_orm(domain_obj) -> model`, `from_orm(model) -> domain_obj`。

```python
_TASK_TYPE_REGISTRY: dict[str, type[Task]] = {
    "standard": StandardTask,
    "custom": CustomTask,
    "package": PackageTask,
    "composite": CompositeTask,
}


def task_to_orm(task: Task) -> TaskModel:
    """领域 Task → ORM TaskModel。"""
    return TaskModel(
        task_id=task.task_id,
        task_type=task.task_type(),
        demander_id=task.demander_id,
        domain_tag=task.domain_tag.value,
        title=task.title,
        description=task.description,
        status=task.status.value,
        supplier_id=task.supplier_id,
        assigned_resource_id=task.assigned_resource_id,
        parent_task_id=task.parent_task_id,
        custom_fields=task.custom_fields,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def task_from_orm(model: TaskModel) -> Task:
    """ORM TaskModel → 领域 Task（按 task_type 重建对应子类）。"""
    cls = _TASK_TYPE_REGISTRY.get(model.task_type, StandardTask)
    task = cls(
        demander_id=model.demander_id,
        domain_tag=DomainTag.of(model.domain_tag),
        title=model.title,
        description=model.description,
    )
    task.task_id = model.task_id
    task.status = TaskStatus(model.status)
    task.supplier_id = model.supplier_id
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
    composite.dependencies = dependencies
    composite.subtasks = subtasks
    return composite
```

### 关键设计点

- ORM 模型用 SQLAlchemy 2.0 的 `DeclarativeBase` + `Mapped` 类型注解风格
- JSONB 字段直接映射 Python dict，无需额外序列化
- 转换器是纯函数，无副作用，易于测试
- `task_from_orm` 按 `task_type` 重建对应子类（StandardTask/CustomTask/CompositeTask）
- CompositeTask 重建需要额外查询 `composite_dependencies` 表和子任务

---

## 4. 仓储实现

### 4.1 PostgresRepositoryBundle（入口）

```python
class PostgresRepositoryBundle:
    """PostgreSQL 仓储套件，提供 6 个仓储 + 事件仓储。"""

    def __init__(self, dsn: str, echo: bool = False) -> None:
        self.engine = create_engine(
            dsn,
            echo=echo,
            pool_pre_ping=True,        # 自动检测断连
            pool_size=10,              # 连接池大小
            max_overflow=20,           # 最大溢出
            pool_recycle=3600,         # 1 小时回收连接
            pool_timeout=30,           # 获取连接超时 30s
        )
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

        self.task_repo = PostgresTaskRepository(self.SessionFactory)
        self.resource_repo = PostgresResourceRepository(self.SessionFactory)
        self.deal_repo = PostgresDealRepository(self.SessionFactory)
        self.user_repo = PostgresUserRepository(self.SessionFactory)
        self.trust_repo = PostgresTrustRepository(self.SessionFactory)
        self.event_repo = PostgresEventRepository(self.SessionFactory)

    @contextmanager
    def transaction(self) -> Session:
        """跨仓储的事务上下文（用于复合任务的原子操作）。"""
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

### 4.2 PostgresTaskRepository（代表性实现）

```python
class PostgresTaskRepository(TaskRepository):
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

### 4.3 PostgresEventRepository（事件日志，支持回放）

```python
class PostgresEventRepository(EventRepository):
    def append(self, event: Event) -> None:
        with self._session() as session:
            model = EventModel(
                event_type=event.type.value,
                source_layer=event.source_layer,
                task_id=event.payload.get("task_id"),
                deal_id=event.payload.get("deal_id"),
                user_id=event.payload.get("user_id"),
                payload=event.payload,
                created_at=event.timestamp,
            )
            session.add(model)

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

### 4.4 PostgresTrustRepository（domain 隔离查询）

`TrustRepository` 接口的 `find_profile(user_id)` 只接受 `user_id`。Postgres 实现需要支持 domain 隔离，新增 `find_profile_by_domain(user_id, domain_tag)` 方法（接口扩展，InMemory 实现同步补充）：

```python
class PostgresTrustRepository(TrustRepository):
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
```

### 4.5 UMCPServer 集成

```python
# server.py 新增方法
def use_postgres_repositories(
    self, dsn: str, echo: bool = False
) -> PostgresRepositoryBundle:
    """使用 PostgreSQL 仓储（生产环境）。"""
    bundle = PostgresRepositoryBundle(dsn, echo)
    self.task_repo = bundle.task_repo
    self.resource_repo = bundle.resource_repo
    self.deal_repo = bundle.deal_repo
    self.user_repo = bundle.user_repo
    self.trust_repo = bundle.trust_repo
    self.event_repo = bundle.event_repo
    self.event_bus.subscribe_all(self.event_repo.append)
    self._postgres_bundle = bundle  # 持有引用以便 dispose
    return bundle

def dispose(self) -> None:
    """释放资源（关闭 DB 连接池）。"""
    if hasattr(self, "_postgres_bundle"):
        self._postgres_bundle.dispose()
```

### 关键设计点

- 每个仓储方法用 `_session()` 上下文管理器，自动 commit/rollback/close
- `save` 用 `session.merge()` 实现 upsert（存在则更新，不存在则插入）
- `find_by_status` 支持 domain_tag 过滤，复用索引 `idx_tasks_status`
- `update_status` 用 UPDATE 语句（比 merge 高效），rowcount=0 抛 KeyError（与 InMemory 一致）
- `EventRepository.replay` 支持 task_id/deal_id/user_id 三种聚合 ID 过滤
- `TrustRepository` 的 domain 隔离在 repo 层通过 `find_profile_by_domain` 实现（接口扩展）
- 连接池用 `pool_pre_ping` 防止使用断连，`pool_recycle` 防止长连接超时

---

## 5. 复合任务智能恢复

### 5.1 恢复时机

`server.start()` 时自动触发，对调用方透明。

### 5.2 UMCPServer.recover_composite_tasks()

```python
def recover_composite_tasks(self) -> dict[str, int]:
    """启动时智能恢复未终态的复合任务。

    返回统计：{"recovered": N, "redispatched": M, "marked_timeout": K}
    """
    stats = {"recovered": 0, "redispatched": 0, "marked_timeout": 0}

    # 1. 查询所有未终态的 CompositeTask（逐个状态查询并合并）
    non_terminal_statuses = [
        TaskStatus.DRAFT, TaskStatus.MATCHING,
        TaskStatus.PUBLISHED, TaskStatus.ASSIGNED,
        TaskStatus.IN_PROGRESS,
    ]
    composites: list[CompositeTask] = []
    for status in non_terminal_statuses:
        tasks = self.task_repo.find_by_status(status.value)
        composites.extend(
            c for c in tasks if c.task_type() == "composite"
        )

    for composite in composites:
        stats["recovered"] += 1
        self._recover_single_composite(composite, stats)

    return stats


def _recover_single_composite(self, composite: CompositeTask, stats: dict) -> None:
    """恢复单个复合任务。"""
    # 2. 重新绑定 EventBus（订阅 SUBTASK_* 事件）
    composite.bind_event_bus(self.event_bus)

    # 3. 重新注册 TASK_COMPLETED 桥接
    self._register_composite_bridge(composite)

    # 4. 遍历子任务，按当前状态分类处理
    for subtask in composite.subtasks:
        if TaskStatus.is_terminal(subtask.status):
            continue  # 已终态，跳过

        if subtask.status == TaskStatus.DRAFT:
            # 4a. DRAFT → 重新派发
            self._execute_subtask_by_domain(subtask)
            stats["redispatched"] += 1

        elif subtask.status in (TaskStatus.MATCHING, TaskStatus.PUBLISHED):
            # 4b. 匹配中/已发布但未指派 → 重新匹配
            self._execute_subtask_by_domain(subtask)
            stats["redispatched"] += 1

        elif subtask.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
            # 4c. 已指派/执行中但未完成 → 标记待超时
            #    （不立即取消，等待超时机制在阶段五D实现）
            #    当前阶段：记录日志，标记 custom_fields["_pending_timeout"]
            subtask.custom_fields["_pending_timeout"] = datetime.utcnow().isoformat()
            self.task_repo.save(subtask)
            stats["marked_timeout"] += 1

    # 5. 检查是否所有子任务已终态（可能在恢复过程中全部完成）
    if all(TaskStatus.is_terminal(s.status) for s in composite.subtasks):
        if any(s.status == TaskStatus.CANCELLED for s in composite.subtasks):
            composite._fail_composite()
        else:
            composite._complete_composite()
```

### 5.3 _register_composite_bridge（提取自 execute_composite，便于复用）

```python
def _register_composite_bridge(self, composite: CompositeTask) -> None:
    """为复合任务注册 TASK_COMPLETED → SUBTASK_* 桥接（恢复时复用）。"""
    subtask_ids = {s.task_id for s in composite.subtasks}

    def _bridge_to_subtask_event(event: Event) -> None:
        task_id = event.payload.get("task_id")
        if task_id not in subtask_ids:
            return
        subtask = composite.find_subtask(task_id)
        if event.payload.get("cancelled"):
            composite.emit_subtask_event(subtask, EventType.SUBTASK_CANCELLED)
        else:
            composite.emit_subtask_event(subtask, EventType.SUBTASK_COMPLETED)
        self._dispatch_ready_subtasks(composite)
        if TaskStatus.is_terminal(composite.status):
            self.event_bus.unsubscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)

    self.event_bus.subscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)
```

### 5.4 server.start() 集成

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
            print(
                f"[UMCPServer] 恢复 {stats['recovered']} 个复合任务"
                f"（重新派发 {stats['redispatched']}，标记待超时 {stats['marked_timeout']}）",
                file=sys.stderr,
            )

    print(f"[UMCPServer] 协议栈已启动。已加载插件: {[p.name for p in self._plugins] or '<无>'}")
    self._started = True
```

### 5.5 关键设计点

- 恢复在 `start()` 时自动触发，对调用方透明
- DRAFT/MATCHING/PUBLISHED 子任务重新派发（走完整匹配流程）
- ASSIGNED/IN_PROGRESS 子任务标记 `_pending_timeout`，等阶段五 D 的超时机制处理
- 已终态子任务跳过（COMPLETED/CANCELLED 不动）
- 恢复后检查是否所有子任务已终态（可能在恢复中全部完成）
- `_register_composite_bridge` 从 `execute_composite` 提取为独立方法，避免代码重复
- 恢复统计返回 dict，便于日志和测试断言

### 5.6 边界情况处理

- 重启时子任务的 `assigned_resource_id` 可能已失效（资源下线）→ 重新匹配会失败 → cancel → 失败传播
- 重启时多个复合任务同时恢复 → 串行处理（避免并发问题）
- 重启时事件桥接重新注册 → 与 `execute_composite` 一致的生命周期管理

---

## 6. 事务保证与错误处理

### 6.1 事务边界原则

每个仓储方法是一个事务单元（`_session()` 上下文已保证）。复合任务的"状态转移 + 事件发布"需要跨多个仓储操作，无法在单个 DB 事务中完成（事件通过 EventBus 异步分发）。

**解决方案：先持久化状态，再发布事件。** 如果事件发布失败，状态已持久化，可通过事件日志恢复。

### 6.2 execute_composite 的事务改造

```python
def execute_composite(self, composite: CompositeTask) -> None:
    # ... 校验逻辑不变

    # 1. 持久化父任务和子任务（原子事务）
    if isinstance(self.task_repo, PostgresTaskRepository):
        self._persist_composite_atomic(composite)
    else:
        # InMemory 路径，保持原行为
        self.task_repo.save(composite)
        for sub in composite.subtasks:
            self.task_repo.save(sub)

    # 2. 绑定 EventBus（事件订阅，不涉及 DB）
    composite.bind_event_bus(self.event_bus)

    # 3. 发布父任务（内存状态转移 + 事件发布）
    composite.publish()

    # 4. 注册桥接 + 派发子任务（与原逻辑一致）
    self._register_composite_bridge(composite)
    self._dispatch_ready_subtasks(composite)


def _persist_composite_atomic(self, composite: CompositeTask) -> None:
    """原子持久化复合任务及其子任务和依赖关系。"""
    if not hasattr(self, "_postgres_bundle"):
        return
    with self._postgres_bundle.transaction() as session:
        session.merge(task_to_orm(composite))
        for sub in composite.subtasks:
            session.merge(task_to_orm(sub))
        for sub_id, deps in composite.dependencies.items():
            for dep_id in deps:
                session.merge(CompositeDependencyModel(
                    composite_task_id=composite.task_id,
                    subtask_id=sub_id,
                    depends_on_id=dep_id,
                ))
```

### 6.3 错误处理策略

| 错误场景 | 处理方式 |
|---------|---------|
| DB 连接失败 | `create_engine(pool_pre_ping=True)` 自动检测断连并重连 |
| 事务提交失败 | `_session()` 自动 rollback，异常向上传播 |
| `save` 时唯一约束冲突 | `IntegrityError` 向上传播，调用方处理 |
| `find_by_id` 不存在 | 返回 `None`（与 InMemory 一致） |
| `update_status` 不存在 | 抛 `KeyError`（与 InMemory 一致） |
| 事件持久化失败 | 日志告警，但不阻塞主流程（事件日志是审计用，非强一致） |
| 恢复时子任务资源失效 | 重新匹配失败 → cancel → 失败传播（正常流程） |

---

## 7. 迁移管理与测试策略

### 7.1 Alembic 迁移配置

```
migrations/
  alembic.ini
  env.py                       # 从环境变量读取 DB URL，导入 Base.metadata
  versions/
    001_init_schema.py         # 创建 7 张表 + 索引
    002_seed_domains.py        # 种子数据（ride_hailing、group_buying 等域）
```

### 7.2 测试策略（4 层）

| 层级 | 测试目标 | 测试数 | 关键场景 |
|------|---------|-------|---------|
| **L1: 转换器单元测试** | 领域对象 ↔ ORM 模型双向转换 | 12 | Task/Resource/Deal/User/Trust/Event 各 2 个（to_orm + from_orm） |
| **L2: 仓储 CRUD 测试** | 6 个仓储的增删改查 + domain 隔离 | 30 | save/find_by_id/find_by_xxx/update_status + TrustRepository domain 隔离 |
| **L3: 复合任务恢复测试** | 模拟重启后恢复 | 6 | DRAFT 重派/MATCHING 重匹配/IN_PROGRESS 标记/全终态完成/有 CANCELLED 立即失败/统计正确 |
| **L4: 端到端持久化测试** | 启动→执行→重启→恢复→继续 | 5 | 正常流程持久化/重启恢复继续执行/重启后子任务资源失效/事务回滚/事件日志回放 |

**总计新增 ≥53 个测试。** 442 → ≥490 passed。

### 7.3 pytest fixture（`tests/conftest.py`）

```python
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from umcp_core.repositories.postgres.models import Base
from umcp_core.repositories.postgres.bundle import PostgresRepositoryBundle

PG_TEST_DSN = os.getenv(
    "TEST_DATABASE_URL", "postgresql://umcp:umcp@localhost:5432/umcp_test"
)


@pytest.fixture(scope="session")
def pg_engine():
    """会话级 PostgreSQL 引擎，所有 PG 测试共享。"""
    engine = create_engine(PG_TEST_DSN, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    """函数级 DB session，每个测试自动回滚（隔离）。"""
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    session.begin_nested()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def pg_bundle(pg_engine):
    """函数级仓储套件，测试后清空数据。"""
    bundle = PostgresRepositoryBundle(PG_TEST_DSN)
    yield bundle
    with bundle.engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            conn.execute(text(f"TRUNCATE {table.name} CASCADE"))
        conn.commit()
    bundle.dispose()


@pytest.fixture
def server_with_pg(pg_bundle):
    """带 PostgreSQL 的 UMCPServer。"""
    from umcp_core.server import UMCPServer
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
```

### 7.4 关键设计点

- `pg_session` fixture 用嵌套事务 + 外层 rollback，保证测试间完全隔离
- `pg_bundle` fixture 用 TRUNCATE 清空，适合需要真实 commit 的恢复测试
- PG 测试需要环境变量 `TEST_DATABASE_URL`，CI 配置 PostgreSQL 服务
- 恢复测试用"强制改状态"模拟中断，验证恢复逻辑正确性
- 端到端测试用"新 server 实例"模拟重启，验证真实恢复场景

---

## 8. 验收标准与实施计划

### 8.1 验收标准

| 维度 | 标准 |
|------|------|
| **测试** | 442 → ≥490 passed（新增 ≥48：转换器 12 + 仓储 30 + 恢复 6 + 端到端 5） |
| **现有测试** | 零回归（442 passed 全部通过，InMemory 路径不受影响） |
| **核心库改动** | `server.py` 新增 `use_postgres_repositories`/`recover_composite_tasks`/`dispose`；`repositories/` 新增 `postgres/` 子包；`core/`/`events/`/`layers/` 零修改 |
| **接口扩展** | `repositories/interfaces.py` 的 `TrustRepository` 新增 `find_profile_by_domain(user_id, domain_tag)` 方法（InMemory 实现同步补充）；其余接口不变 |
| **插件零修改** | `plugins/ride_hailing`/`plugins/group_buying` 不变 |
| **InMemory 兼容** | `use_in_memory_repositories` 路径保持原行为，开发调试仍可用 |
| **依赖** | 新增 `sqlalchemy>=2.0`、`alembic`、`psycopg[binary]` |
| **Docker** | `docker-compose.yml` 提供 PostgreSQL 服务，`make test-pg` 跑 PG 测试 |

### 8.2 新增依赖（`pyproject.toml`）

```toml
[project.optional-dependencies]
postgres = [
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg[binary]>=3.1.0",
]
dev = [
    # ... 现有 dev 依赖
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg[binary]>=3.1.0",
]
```

### 8.3 docker-compose.yml

```yaml
services:
  postgres:
    image: postgres:16-alpine
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

### 8.4 实施计划概览（8 个任务）

| 任务 | 内容 | 新增测试 | 关键文件 |
|------|------|---------|---------|
| 1. ORM 模型 + 转换器 | 7 个 ORM 模型 + 6 对转换器 | 12 | `postgres/models.py`、`postgres/converters.py` |
| 2. TaskRepository 实现 | `PostgresTaskRepository` | 8 | `postgres/task_repo.py` |
| 3. Resource/Deal/User 仓储 | 3 个仓储实现 | 12 | `postgres/resource_repo.py` 等 |
| 4. TrustRepository 实现 | 含 domain 隔离查询 | 6 | `postgres/trust_repo.py` |
| 5. EventRepository 实现 | 含 `replay()` 回放 | 4 | `postgres/event_repo.py` |
| 6. Bundle + server 集成 | `PostgresRepositoryBundle` + `use_postgres_repositories` + `dispose` | 0 | `postgres/bundle.py`、`server.py` |
| 7. 复合任务恢复 + 事务 | `recover_composite_tasks` + `_persist_composite_atomic` + Alembic 迁移 | 6 | `server.py`、`migrations/` |
| 8. 端到端测试 + Docker | 端到端持久化测试 + docker-compose + pyproject 依赖 | 5 | `tests/test_recovery.py`、`docker-compose.yml`、`pyproject.toml` |

---

## 9. 已知限制

- 复合任务恢复时 ASSIGNED/IN_PROGRESS 子任务仅标记 `_pending_timeout`，真正的超时取消机制在阶段五 D 实现
- SQLite 不支持 JSONB 索引，本阶段仅支持 PostgreSQL（SQLite 支持可后续扩展）
- 事件日志是审计用，非事件溯源（不用于状态重建，状态由业务表重建）
- 单机部署，水平扩展能力在后续阶段实现

---

## 10. 实施记录

（实施后填充：commit 历史、bug 修复、规格修订等）
