# PostgreSQL 持久化（阶段五 A）说明文档

**阶段**：五 A（持久化与生产化）
**适用范围**：`UMCPServer` 通过 PostgreSQL 持久化领域对象、事件日志与复合任务恢复的整套机制
**文档定位**：面向核心库使用者和部署运维人员，完整说明双层架构、ORM 模型、转换器、仓储实现、事务管理、Alembic 迁移、复合任务智能恢复与使用方法。

---

## 一、概述

### 1.1 阶段目标

阶段五 A 的目标是将全内存协议栈改造为 **PostgreSQL 持久化**，支持重启恢复与复合任务智能恢复。核心采用**双层架构**：领域对象（`Task` / `Resource` / `Deal` / `User` / `TrustProfile` / `Event`）与 ORM 模型（`TaskModel` / `ResourceModel` / ...）分离，二者通过纯函数转换器双向映射，领域对象零修改、仓储抽象接口零修改。

### 1.2 解决的问题

在阶段五 A 之前，`UMCPServer` 通过 `use_in_memory_repositories()` 持有全内存仓储（见 `src/umcp_core/server.py:168`），这意味着：

- **重启即丢失**：进程退出后所有任务、资源、交易、信任档案、事件日志全部丢失，无法满足生产环境诉求
- **横向扩展受限**：内存仓储单机独占，多实例之间无共享状态，无法水平扩容
- **复合任务无法恢复**：进程在复合任务执行中崩溃后，子任务处于中间态（DRAFT/MATCHING/IN_PROGRESS），重启后无任何途径继续推进
- **事件无法审计**：EventBus 的事件仅内存广播，无持久化日志，无法回放与审计

### 1.3 核心设计

阶段五 A 通过引入 `repositories/postgres/` 子包与 Alembic 迁移解决上述问题，关键决策如下：

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 数据库 | PostgreSQL 16 | 原生 JSONB 支持、成熟稳定、生产级 |
| ORM | SQLAlchemy 2.0 | `DeclarativeBase` + `Mapped` 类型注解风格、社区主流 |
| 映射策略 | **双层架构**（领域对象 + ORM 模型分离） | 领域对象零修改，ORM 模型可独立演进 |
| 事件存储 | 混合模式（业务表存当前状态 + `events` 表存审计日志） | 业务表服务于查询，events 表服务于审计/回放 |
| 复合任务恢复 | 智能恢复 | 按子任务当前状态分类处理（DRAFT/MATCHING 重派、IN_PROGRESS 标记待超时） |
| 迁移管理 | Alembic | 版本化 schema，支持 upgrade/downgrade |
| 兼容性 | InMemory 路径保留 | 开发调试仍可用 `use_in_memory_repositories()`，PG 路径与 InMemory 路径并存 |

---

## 二、目录结构

阶段五 A 涉及的核心文件与职责：

```
umcp-core/
├── src/umcp_core/
│   ├── repositories/
│   │   ├── interfaces.py                      # 仓储抽象接口（TrustRepository 扩展 find_profile_by_domain）
│   │   ├── in_memory.py                       # InMemory 实现（同步实现 find_profile_by_domain）
│   │   └── postgres/                          # 新增子包
│   │       ├── __init__.py                    # 子包入口，导出 7 个公共类
│   │       ├── models.py                      # 8 个 SQLAlchemy ORM 模型（Base + 8 张表）
│   │       ├── converters.py                  # 领域对象 ↔ ORM 模型转换器（纯函数）
│   │       ├── bundle.py                      # PostgresRepositoryBundle（聚合入口）
│   │       ├── task_repo.py                   # PostgresTaskRepository（含复合任务原子持久化与重建）
│   │       ├── resource_repo.py               # PostgresResourceRepository
│   │       ├── deal_repo.py                   # PostgresDealRepository
│   │       ├── user_repo.py                   # PostgresUserRepository
│   │       ├── trust_repo.py                  # PostgresTrustRepository（含 domain 隔离查询）
│   │       └── event_repo.py                  # PostgresEventRepository（含 replay 回放）
│   └── server.py                              # UMCPServer：use_postgres_repositories / dispose / recover_composite_tasks
│
├── migrations/                                # 新增 Alembic 迁移
│   ├── alembic.ini                            # Alembic 配置（script_location = .）
│   ├── env.py                                 # 从 DATABASE_URL 读取，导入 Base.metadata
│   ├── script.py.mako                         # 迁移脚本模板
│   └── versions/
│       └── 001_init_schema.py                 # 初始 schema（8 张表 + 索引）
│
├── docker-compose.yml                         # PostgreSQL 16 + app 服务定义
│
└── tests/
    ├── conftest.py                            # PG fixture + PG 不可用时自动 skip
    ├── test_postgres_converters.py            # L1 转换器单元测试
    ├── test_postgres_repos.py                 # L2 仓储 CRUD + Bundle + Server 集成测试
    ├── test_recovery.py                       # L3 复合任务智能恢复测试
    └── test_persistence_e2e.py                # L4 端到端持久化测试
```

### 文件职责说明

| 文件 | 职责 |
|------|------|
| `repositories/interfaces.py` | 定义 6 个仓储抽象接口；`TrustRepository` 新增 `find_profile_by_domain(user_id, domain_tag)`（`interfaces.py:139-144`）支持 domain 隔离 |
| `repositories/postgres/models.py` | 定义 `Base` 与 8 个 ORM 模型，对应 8 张数据库表 |
| `repositories/postgres/converters.py` | 领域对象 ↔ ORM 模型的纯函数转换器，含 `_TASK_TYPE_REGISTRY` 按 `task_type` 重建子类 |
| `repositories/postgres/bundle.py` | `PostgresRepositoryBundle`：创建 engine、SessionFactory、6 个仓储实例；提供 `transaction()` 跨仓储事务上下文与 `dispose()` |
| `repositories/postgres/task_repo.py` | `PostgresTaskRepository`：`save` 对 `CompositeTask` 原子持久化子任务与依赖；`_reconstruct_if_composite` 读时按 `parent_task_id` 重建复合任务 |
| `repositories/postgres/resource_repo.py` | `PostgresResourceRepository`：含 `find_available(domain_tag)` 按 domain + IDLE 状态查询 |
| `repositories/postgres/deal_repo.py` | `PostgresDealRepository`：按 task / supplier 查询交易 |
| `repositories/postgres/user_repo.py` | `PostgresUserRepository`：按 user_id / name 查询用户 |
| `repositories/postgres/trust_repo.py` | `PostgresTrustRepository`：`find_profile_by_domain` 实现 domain 隔离；`find_profile` 向后兼容返回任意 domain |
| `repositories/postgres/event_repo.py` | `PostgresEventRepository`：`append` 失败仅告警不阻塞主流程；`replay(aggregate_id)` 支持 task_id/deal_id/user_id 三种聚合回放 |
| `server.py` | 新增 `use_postgres_repositories`（`server.py:122-160`）、`dispose`（`server.py:162-166`）、`_persist_composite_atomic`（`server.py:543-565`）、`recover_composite_tasks`（`server.py:567-597`）、`_recover_single_composite`（`server.py:599-655`）；`start()` 集成恢复（`server.py:668-676`） |
| `migrations/versions/001_init_schema.py` | 初始 schema：8 张表 + 索引（revision="001"） |
| `tests/conftest.py` | `PG_TEST_DSN` 环境变量、`_pg_available()` 探测、`pytest_collection_modifyitems` 自动 skip、`pg_engine` / `pg_bundle` fixture |

---

## 三、核心设计

### 3.1 双层架构

阶段五 A 采用**双层架构**：领域对象与 ORM 模型分离，二者通过转换器双向映射。领域对象（`Task` / `Resource` 等）不依赖 SQLAlchemy，ORM 模型可独立演进。

```
┌──────────────────────────────────────────────────────┐
│                     UMCPServer                        │
│         use_postgres_repositories(dsn)                │
│         recover_composite_tasks()  ← start() 触发     │
├──────────────────────────────────────────────────────┤
│  仓储层（双层架构）                                    │
│  ┌────────────────────────────────────────────────┐  │
│  │  领域对象（Task / Resource / Deal / User / ...）│  │
│  │       ↕  converters（to_orm / from_orm）        │  │
│  │  ORM 模型（TaskModel / ResourceModel / ...）    │  │
│  │       ↕  SQLAlchemy 2.0 Session                 │  │
│  │  PostgreSQL 16                                  │  │
│  └────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────┤
│  事件存储（混合模式）                                  │
│  event_bus.subscribe_all(event_repo.append)          │
│    → events 表（完整事件日志，用于审计/回放）          │
└──────────────────────────────────────────────────────┘
```

设计要点：
1. **领域对象零修改**：`Task` / `Resource` / `Deal` / `User` 等不引入 SQLAlchemy 依赖
2. **仓储接口零修改**：`TaskRepository` / `ResourceRepository` 等 ABC 不变（仅 `TrustRepository` 新增 `find_profile_by_domain` 方法，向后兼容）
3. **转换器是纯函数**：`to_orm(domain_obj) -> model` 与 `from_orm(model) -> domain_obj`，无副作用，易于测试
4. **InMemory 路径保留**：`use_in_memory_repositories()` 行为不变，开发调试仍可用

### 3.2 ORM 模型设计

ORM 模型定义在 `src/umcp_core/repositories/postgres/models.py`，使用 SQLAlchemy 2.0 的 `DeclarativeBase` + `Mapped` 类型注解风格。共 8 张表：

| ORM 模型 | 表名 | 主键 | 用途 | 代码位置 |
|---------|------|------|------|---------|
| `Base` | — | — | 所有模型的 `DeclarativeBase` 基类 | `models.py:18-21` |
| `TaskModel` | `tasks` | `task_id` | 任务（含复合任务和子任务，用 `parent_task_id` 建立层级） | `models.py:24-41` |
| `ResourceModel` | `resources` | `resource_id` | 资源 | `models.py:44-59` |
| `DealModel` | `deals` | `deal_id` | 交易 | `models.py:62-79` |
| `UserModel` | `users` | `user_id` | 用户 | `models.py:82-95` |
| `TrustProfileModel` | `trust_profiles` | `(user_id, domain_tag)` | 信任档案（按 domain 隔离） | `models.py:98-107` |
| `TrustEvaluationModel` | `trust_evaluations` | `(evaluator_id, evaluatee_id, task_id)` | 评价记录 | `models.py:110-121` |
| `EventModel` | `events` | `event_id` (BIGSERIAL) | 事件日志（审计/回放） | `models.py:124-136` |
| `CompositeDependencyModel` | `composite_dependencies` | `(subtask_id, depends_on_id)` | 复合任务 DAG 依赖 | `models.py:139-146` |

`TaskModel` 是复合任务与子任务的统一存储，通过 `parent_task_id` 建立层级关系（`models.py:38`）。`custom_fields` / `capabilities` / `metadata` 等灵活字段用 JSONB 存储（PostgreSQL 原生支持）。`TrustProfileModel` 用复合主键 `(user_id, domain_tag)` 保证 domain 隔离（`models.py:103-104`）。`EventModel` 用 `BIGSERIAL` 自增主键，支持高吞吐事件写入（`models.py:129`）。

### 3.3 Converter 双向转换机制

转换器定义在 `src/umcp_core/repositories/postgres/converters.py`，每个转换器是一对纯函数：`to_orm(domain_obj) -> model` 与 `from_orm(model) -> domain_obj`。

#### 3.3.1 task_type 注册表与子类重建

`_TASK_TYPE_REGISTRY`（`converters.py:27-32`）维护 `task_type` 字符串到领域类的映射，`task_from_orm` 据此重建对应子类：

```python
_TASK_TYPE_REGISTRY: dict[str, type[Task]] = {
    "standard": StandardTask,
    "custom": CustomTask,
    "package": PackageTask,
    "composite": CompositeTask,
}
```

`task_from_orm`（`converters.py:60-79`）按 `model.task_type` 从注册表取类（缺省 `StandardTask`），重建实例后回填 `task_id` / `status` / `assigned_resource_id` / `custom_fields` / 时间戳。

#### 3.3.2 CompositeTask 的特殊重建

`CompositeTask` 的 `dependencies` 和 `subtasks` 需要额外查询重建。`task_from_orm` 只重建基本字段，完整的 CompositeTask 由 `composite_task_from_orm`（`converters.py:82-93`）重建——直接设置 `subtasks` 和 `dependencies` 属性，跳过 DAG 校验以接受已持久化的状态。

依赖关系通过 `dependencies_to_orm` / `dependencies_from_orm`（`converters.py:372-394`）在 `dict[str, list[str]]` 与 `CompositeDependencyModel` 列表之间转换。

#### 3.3.3 抽象类的通用子类兜底

`Resource` 和 `User` 是抽象类，`resource_from_orm`（`converters.py:140-162`）与 `user_from_orm`（`converters.py:232-269`）在函数内部动态定义 `_GenericResource` / `_GenericUser` 子类实例兜底，并按 `resource_type` / `user_type` 回填。`User` 的 `roles` 序列化为 `{role_type: {"permissions": [...]}}` 字典，恢复时按 `demander` / `supplier` 重建带 `permissions` 属性的角色子类。

### 3.4 RepositoryBundle 聚合入口

`PostgresRepositoryBundle`（`src/umcp_core/repositories/postgres/bundle.py:19-70`）是 PG 仓储的聚合入口，对标 `InMemoryRepositoryBundle`：

```python
class PostgresRepositoryBundle:
    def __init__(self, dsn, echo=False, pool_size=10, max_overflow=20,
                 pool_recycle=3600, pool_timeout=30) -> None:
        self.engine = create_engine(
            dsn, echo=echo, pool_pre_ping=True,
            pool_size=pool_size, max_overflow=max_overflow,
            pool_recycle=pool_recycle, pool_timeout=pool_timeout,
        )
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        # 6 个仓储 + 事件仓储
        self.task_repo = PostgresTaskRepository(self.SessionFactory)
        ...
```

设计要点：
- **连接池**：`pool_pre_ping=True` 自动检测断连；`pool_recycle=3600` 1 小时回收连接防超时；`pool_timeout=30` 获取连接超时 30s（`bundle.py:36-44`）
- **`expire_on_commit=False`**：commit 后对象不过期，避免跨事务访问触发额外查询
- **`Base.metadata.create_all`**：开发期自动建表；生产期用 Alembic 迁移管理
- **`transaction()` 上下文**（`bundle.py:56-67`）：跨仓储的原子事务，commit/rollback/close 自动管理
- **`dispose()`**（`bundle.py:69-70`）：释放连接池

### 3.5 事务管理（session scope）

每个仓储方法是一个事务单元，通过 `_session()` 上下文管理器（如 `task_repo.py:29-40`）自动 commit/rollback/close：

```python
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
```

**事务边界原则**：每个仓储方法独立事务。复合任务的"状态转移 + 事件发布"无法在单个 DB 事务中完成（事件通过 EventBus 异步分发），解决方案是**先持久化状态，再发布事件**——若事件发布失败，状态已持久化，可通过事件日志恢复。

复合任务的跨仓储原子持久化通过 `bundle.transaction()` 完成，见 `server.py:543-565` 的 `_persist_composite_atomic`：

```python
def _persist_composite_atomic(self, composite: CompositeTask) -> None:
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
        for sub_id, deps in composite.dependencies.items():
            for dep_id in deps:
                session.merge(CompositeDependencyModel(
                    composite_task_id=composite.task_id,
                    subtask_id=sub_id, depends_on_id=dep_id,
                ))
```

`save` 用 `session.merge()` 实现 upsert（存在则更新，不存在则插入）；`update_status` 用 UPDATE 语句（比 merge 高效），`rowcount==0` 抛 `KeyError`（与 InMemory 一致，见 `task_repo.py:98-106`）。

### 3.6 复合任务的原子持久化与读时重建

`PostgresTaskRepository.save`（`task_repo.py:42-72`）对 `CompositeTask` 做了特殊处理：在同一事务内设置子任务的 `parent_task_id`、保存父任务、所有子任务与依赖关系：

```python
def save(self, task: Task) -> Task:
    is_composite = task.task_type() == "composite"
    if is_composite:
        for sub in task.subtasks:
            sub.parent_task_id = task.task_id
    with self._session() as session:
        session.merge(task_to_orm(task))
        if is_composite:
            for sub in task.subtasks:
                session.merge(task_to_orm(sub))
            for sub_id, deps in task.dependencies.items():
                for dep_id in deps:
                    session.merge(CompositeDependencyModel(...))
        return task
```

读时通过 `_reconstruct_if_composite`（`task_repo.py:108-130`）透明重建：若 `task_type == "composite"`，按 `parent_task_id` 查询子任务、按 `composite_task_id` 查询依赖，调用 `composite_task_from_orm` 拼装完整 `CompositeTask`。`find_by_id` / `find_by_demander` / `find_by_status` / `list_all` 均走此路径，调用方无感知。

### 3.7 事件日志回放机制

`PostgresEventRepository`（`event_repo.py`）实现事件持久化与回放：

- **`append`**（`event_repo.py:37-45`）：追加事件到 `events` 表。**失败时仅告警不抛异常**——事件日志是审计用，非强一致，不阻塞主流程：

```python
def append(self, event: Event) -> None:
    try:
        with self._session() as session:
            session.add(event_to_orm(event))
    except Exception as e:
        import sys
        print(f"[PostgresEventRepository] 事件持久化失败: {e}", file=sys.stderr)
```

- **`replay(aggregate_id=None)`**（`event_repo.py:47-60`）：按 `event_id` 升序回放事件。传入 `aggregate_id` 时用 `OR` 匹配 `task_id` / `deal_id` / `user_id` 三种聚合，支持按聚合回放。

事件日志是**审计用**，非事件溯源——状态由业务表重建，events 表只用于追溯。

### 3.8 TrustRepository 的 domain 隔离

`TrustRepository` 接口（`interfaces.py:120-144`）扩展了 `find_profile_by_domain(user_id, domain_tag)` 方法，支持 domain 隔离查询。`TrustProfileModel` 用复合主键 `(user_id, domain_tag)` 保证同一用户在不同 domain 的信任档案隔离存储。

`PostgresTrustRepository`（`trust_repo.py`）实现两个查询方法：
- `find_profile(user_id)`（`trust_repo.py:48-55`）：返回该用户的任意一个 domain 的 profile，向后兼容
- `find_profile_by_domain(user_id, domain_tag)`（`trust_repo.py:57-67`）：按 domain 精确查询

`InMemoryTrustRepository` 同步实现 `find_profile_by_domain`，存储改为按 `(user_id, domain_tag)` 元组索引，保持两条路径行为一致。

### 3.9 Alembic 迁移管理

迁移文件位于 `migrations/`：

| 文件 | 职责 |
|------|------|
| `alembic.ini` | Alembic 配置；`script_location = .`（在 migrations 目录下执行）；默认 `sqlalchemy.url = postgresql://umcp:umcp@localhost:5432/umcp_dev` |
| `env.py` | 从环境变量 `DATABASE_URL` 覆盖 DB URL（`env.py:17-19`）；导入 `Base.metadata` 作为 `target_metadata`（`env.py:24`）；支持 offline / online 两种迁移模式 |
| `script.py.mako` | 迁移脚本模板 |
| `versions/001_init_schema.py` | 初始 schema：8 张表 + 索引（revision="001"，down_revision=None） |

`001_init_schema.py` 的 `upgrade()`（`001_init_schema.py:19-134`）创建 `tasks` / `resources` / `deals` / `users` / `trust_profiles` / `trust_evaluations` / `events` / `composite_dependencies` 共 8 张表，并建立关键索引：

- `idx_tasks_demander` / `idx_tasks_status` / `idx_tasks_parent`：按 demander、status+domain、parent_task_id 查询任务
- `idx_resources_supplier` / `idx_resources_available`：按 supplier、domain+status 查询资源
- `idx_deals_task` / `idx_deals_supplier`：按 task、supplier 查询交易
- `idx_evaluations_user`：按 evaluatee+domain 查询评价
- `idx_events_task` / `idx_events_deal` / `idx_events_user` / `idx_events_type_time`：事件按聚合与类型+时间查询
- `idx_deps_composite`：按 composite_task_id 查询依赖

`downgrade()`（`001_init_schema.py:137-145`）按反向依赖顺序 drop 所有表。

### 3.10 UMCPServer 集成

`UMCPServer` 新增 PG 装配与生命周期方法：

#### `use_postgres_repositories`（`server.py:122-160`）

```python
def use_postgres_repositories(self, dsn, echo=False, pool_size=10,
                              max_overflow=20, pool_recycle=3600,
                              pool_timeout=30) -> PostgresRepositoryBundle:
    bundle = PostgresRepositoryBundle(dsn, echo, pool_size=pool_size,
                                       max_overflow=max_overflow,
                                       pool_recycle=pool_recycle,
                                       pool_timeout=pool_timeout)
    self.task_repo = bundle.task_repo
    self.resource_repo = bundle.resource_repo
    ...
    self.event_bus.subscribe_all(self.event_repo.append)  # 事件落库
    self._postgres_bundle = bundle
    return bundle
```

#### `dispose`（`server.py:162-166`）

释放连接池，删除 `_postgres_bundle` 引用。

#### `recover_composite_tasks`（`server.py:567-597`）

启动时智能恢复未终态复合任务，返回统计 `{"recovered": N, "redispatched": M, "marked_timeout": K}`。查询 5 个非终态状态（DRAFT/MATCHING/PUBLISHED/ASSIGNED/IN_PROGRESS）的 `CompositeTask`，逐个调用 `_recover_single_composite`。

#### `_recover_single_composite`（`server.py:599-655`）

按子任务状态分类处理：

| 子任务状态 | 处理方式 | 统计字段 |
|-----------|---------|---------|
| 已终态（COMPLETED/CANCELLED） | 跳过 | — |
| DRAFT / MATCHING / PUBLISHED | 重新绑定 EventBus + 重新派发（`_execute_subtask_by_domain`） | `redispatched` |
| ASSIGNED / IN_PROGRESS | 标记 `custom_fields["_pending_timeout"]` 并保存（等阶段五 D 超时机制） | `marked_timeout` |

恢复后检查是否所有子任务已终态：全部 COMPLETED 则父任务完成，有 CANCELLED 则父任务失败。

#### `start` 集成（`server.py:661-682`）

`start()` 在校验组件后、设置 `_started` 前自动触发 `recover_composite_tasks()`，对调用方透明：

```python
def start(self) -> None:
    ...
    self._validate_required_components()
    if self.task_repo is not None:
        stats = self.recover_composite_tasks()
        if stats["recovered"] > 0:
            print(f"[UMCPServer] 恢复 {stats['recovered']} 个复合任务"
                  f"（重新派发 {stats['redispatched']}，标记待超时 {stats['marked_timeout']}）",
                  file=sys.stderr)
    ...
    self._started = True
```

---

## 四、关键实现细节（含已修复的坑）

### 4.1 `metadata` 列名与 SQLAlchemy 2.0 保留属性冲突

**问题**：`ResourceModel` / `DealModel` / `UserModel` 都需要 `metadata` 列存储 JSONB 扩展字段。但 `metadata` 是 SQLAlchemy 2.0 `DeclarativeBase` 的保留属性（`Base.metadata` 是 `MetaData` 对象，用于收集所有表定义）。若直接用 `metadata: Mapped[...] = mapped_column(JSONB, ...)`，SQLAlchemy 在类构造时会覆盖 `Base.metadata`，导致模型注册异常。

**修复**：Python 属性改用 `metadata_`（带下划线），数据库列名仍为 `metadata`，通过 `mapped_column` 的第一参数显式指定列名：

```python
# models.py:55-57（ResourceModel）
# 'metadata' 是 DeclarativeBase 的保留属性名，Python 属性用 metadata_，
# 数据库列名仍为 metadata（由 mapped_column 第一参数指定）
metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
```

同样的处理见 `models.py:75-77`（DealModel）与 `models.py:91-93`（UserModel）。

**转换器同步适配**：`converters.py` 中所有读写 `metadata` 的转换器都使用 `metadata_` Python 属性：

| 转换器 | to_orm 写入 | from_orm 读取 | 代码位置 |
|--------|------------|--------------|---------|
| `resource_to_orm` / `resource_from_orm` | `metadata_=resource.metadata` | `model.metadata_` | `converters.py:134,157` |
| `deal_to_orm` / `deal_from_orm` | `metadata_=deal.metadata` | `model.metadata_` | `converters.py:181,196` |
| `user_to_orm` / `user_from_orm` | `metadata_=getattr(user, "metadata", {})` | `model.metadata_` | `converters.py:225,250` |

### 4.2 Resource / User 转换器 round-trip 测试覆盖

`Resource` 和 `User` 是抽象类，转换器需要在函数内部动态定义子类兜底。`tests/test_postgres_converters.py` 用专门的 round-trip 测试覆盖这两个边界：

- `TestResourceConverter.test_resource_roundtrip`（`test_postgres_converters.py:254-290`）：验证 `Capability` 列表、`metadata`、`status` 等 JSONB 字段的双向保留，并断言 `model.metadata_ == {"location": "北京"}` 与 `restored.metadata == {"location": "北京"}`（验证 `metadata_` ↔ `metadata` 映射正确）
- `TestResourceConverter.test_resource_with_expiry_capability`（`test_postgres_converters.py:292-310`）：验证带 `expiry` 的 `Capability` 的 ISO 格式序列化/反序列化
- `TestUserConverter.test_user_roundtrip`（`test_postgres_converters.py:314-330`）：验证 `roles` 字典序列化、`active_role.role_type` 恢复
- `TestUserConverter.test_user_without_roles`（`test_postgres_converters.py:332-342`）：验证无角色时 `user_type="unknown"`、`roles={}` 的兜底

### 4.3 PG 不可用时自动 skip 测试

`tests/conftest.py` 实现 PG 服务的探测与自动跳过，确保无 PG 环境下测试套件仍可运行：

1. **`PG_TEST_DSN`**（`conftest.py:22-24`）：从 `TEST_DATABASE_URL` 环境变量读取，默认 `postgresql://umcp:umcp@localhost:5432/umcp_dev`
2. **`_pg_available()`**（`conftest.py:27-37`）：尝试连接并执行 `SELECT 1` + `Base.metadata.create_all`，失败返回 `False`
3. **`PG_AVAILABLE`**（`conftest.py:40`）：模块级常量，会话级探测一次
4. **`pytest_collection_modifyitems`**（`conftest.py:43-50`）：若 `PG_AVAILABLE=False`，给所有标记 `@pytest.mark.postgres` 的测试加 skip marker

PG 测试标记通过 `pytest_configure`（`conftest.py:17-18`）注册 `postgres` marker。`test_postgres_repos.py` 与 `test_recovery.py` 用模块级 `pytestmark = pytest.mark.postgres` 整体标记；`test_persistence_e2e.py` 则逐方法标记，使 `test_in_memory_path_unaffected` 不被跳过（见 `test_persistence_e2e.py:15-16` 注释）。

### 4.4 复合任务读时重建的透明性

`PostgresTaskRepository` 的所有读方法（`find_by_id` / `find_by_demander` / `find_by_status` / `list_all`）都通过 `_reconstruct_if_composite`（`task_repo.py:108-130`）透明重建 `CompositeTask`。调用方拿到的是完整的 `CompositeTask` 实例（含 `subtasks` 和 `dependencies`），与内存仓储行为一致，无需感知持久化细节。这是 `recover_composite_tasks` 能直接遍历 `composite.subtasks` 的前提。

### 4.5 事件持久化失败的容错策略

`PostgresEventRepository.append`（`event_repo.py:37-45`）用 try/except 包裹整个事务，失败时仅打印 stderr 告警。这是因为事件日志是审计用，非强一致——主流程（任务状态转移）已持久化，事件丢失不影响业务正确性，可通过业务表重建状态。该策略与规格 §6.3 的错误处理表一致。

### 4.6 InMemory 路径的向后兼容

`_persist_composite_atomic`（`server.py:543-565`）通过 `hasattr(self, "_postgres_bundle")` 判断路径：PG 路径走 `bundle.transaction()` 原子持久化；InMemory 路径逐个 `task_repo.save`，保持阶段四 C 的原行为。`recover_composite_tasks` 在 `task_repo is None` 时直接返回全 0 统计（`server.py:577-578`），避免对 InMemory 路径造成副作用。

---

## 五、使用方法

### 5.1 启动 PostgreSQL

通过 docker compose 启动 PostgreSQL 16 服务（`docker-compose.yml`）：

```bash
docker compose up -d postgres
# 容器：umcp_postgres
# 用户：umcp / 密码：umcp / 默认库：umcp_dev
# 端口：5432
# 数据卷：umcp_pg_data
```

`docker-compose.yml` 同时定义了 `app` 服务（`docker-compose.yml:19-39`），通过 `UMCP_DB_DSN` 环境变量注入连接串，`depends_on` 等待 postgres 健康检查通过。

### 5.2 配置 DATABASE_URL

通过环境变量配置连接串，Alembic 与测试套件均读取此变量：

```bash
# Linux/macOS
export DATABASE_URL="postgresql://umcp:umcp@localhost:5432/umcp_dev"
export TEST_DATABASE_URL="postgresql://umcp:umcp@localhost:5432/umcp_dev"

# Windows PowerShell
$env:DATABASE_URL="postgresql://umcp:umcp@localhost:5432/umcp_dev"
$env:TEST_DATABASE_URL="postgresql://umcp:umcp@localhost:5432/umcp_dev"
```

`migrations/env.py`（`env.py:17-19`）用 `DATABASE_URL` 覆盖 `alembic.ini` 的默认 URL；`tests/conftest.py`（`conftest.py:22-24`）用 `TEST_DATABASE_URL` 配置测试连接。

### 5.3 运行迁移

在 `migrations/` 目录下执行 Alembic 迁移（`alembic.ini` 的 `script_location = .`）：

```bash
cd migrations
alembic upgrade head      # 创建 8 张表 + 索引
alembic current           # 查看当前版本
alembic downgrade base    # 回滚到初始（drop 所有表）
```

迁移脚本 `001_init_schema.py`（revision="001"）创建初始 schema。开发期也可由 `PostgresRepositoryBundle.__init__` 的 `Base.metadata.create_all` 自动建表（`bundle.py:46`），生产期推荐用 Alembic 管理。

### 5.4 在 UMCPServer 中装配 PG 仓储

```python
from umcp_core.server import UMCPServer

server = UMCPServer()
server.use_postgres_repositories(
    dsn="postgresql://umcp:umcp@localhost:5432/umcp_dev",
    echo=False,          # 是否打印 SQL（调试用）
    pool_size=10,        # 连接池常驻大小
    max_overflow=20,     # 连接池溢出上限
    pool_recycle=3600,   # 连接回收周期（秒）
    pool_timeout=30,     # 获取连接超时（秒）
)
# 仓储已注入：server.task_repo / resource_repo / deal_repo / user_repo / trust_repo / event_repo
# 事件已订阅：event_bus.subscribe_all(event_repo.append)

server.start()
# [UMCPServer] 恢复 N 个复合任务（重新派发 M，标记待超时 K）  ← 若有未终态复合任务
# [UMCPServer] 协议栈已启动。已加载插件: [...]

# 退出时释放连接池
server.dispose()
```

### 5.5 完整示例：任务持久化与重启恢复

```python
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus

# server 1：创建任务并持久化
server1 = UMCPServer()
server1.use_postgres_repositories("postgresql://umcp:umcp@localhost:5432/umcp_dev")
task = StandardTask(
    demander_id="user-1",
    domain_tag=DomainTag.of("ride"),
    title="打车到机场",
)
server1.task_repo.save(task)        # upsert 落库
task_id = task.task_id
server1.dispose()                    # 模拟进程退出

# server 2：新实例（模拟重启），从 PG 读取
server2 = UMCPServer()
server2.use_postgres_repositories("postgresql://umcp:umcp@localhost:5432/umcp_dev")
found = server2.task_repo.find_by_id(task_id)
assert found is not None
assert found.demander_id == "user-1"
assert found.title == "打车到机场"
```

### 5.6 事件日志回放

```python
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType

# 发布事件（自动通过 subscribe_all 落库）
server.event_bus.publish(Event(
    type=EventType.TASK_PUBLISHED,
    source_layer="L2",
    payload={"task_id": "task-1", "extra": "data"},
))

# 按聚合 ID 回放
events = server.event_repo.replay("task-1")
assert events[0].payload["task_id"] == "task-1"

# 回放全部事件
all_events = server.event_repo.replay()
```

---

## 六、测试覆盖

阶段五 A 新增 4 个测试文件，共 62 个测试，按 4 层策略组织：

### 6.1 `tests/test_postgres_converters.py`（L1 转换器单元测试，12 个）

不依赖数据库，纯函数测试领域对象 ↔ ORM 模型双向转换。

| 测试类 | 测试 | 验证点 |
|--------|------|--------|
| `TestTaskConverter` | `test_standard_task_roundtrip` | StandardTask to_orm → from_orm 保留 task_id/status/custom_fields 等全部字段 |
| | `test_custom_task_roundtrip` | CustomTask 按 task_type 重建为 CustomTask |
| | `test_composite_task_roundtrip` | CompositeTask 重建需额外传 dependencies 和 subtasks；`composite_task_from_orm` 拼装完整 |
| `TestDealConverter` | `test_deal_roundtrip` | Deal 保留 final_amount/status/metadata |
| `TestTrustProfileConverter` | `test_trust_profile_roundtrip_with_domain` | TrustProfile 保留 domain_tag/overall_score/dimension_scores |
| `TestEvaluationConverter` | `test_evaluation_roundtrip_with_domain` | Evaluation 保留 domain_tag/ratings |
| `TestEventConverter` | `test_event_roundtrip` | Event 保留 event_type/payload |
| `TestDependenciesConverter` | `test_dependencies_roundtrip` | 依赖关系 dict ↔ CompositeDependencyModel 列表双向转换 |
| `TestResourceConverter` | `test_resource_roundtrip` | Resource 保留 capabilities/metadata/status；验证 `metadata_` ↔ `metadata` 映射 |
| | `test_resource_with_expiry_capability` | 带 expiry 的 Capability ISO 格式序列化/反序列化 |
| `TestUserConverter` | `test_user_roundtrip` | User 的 roles 字典序列化、active_role 恢复 |
| | `test_user_without_roles` | 无角色时 user_type="unknown"、roles={} 兜底 |

### 6.2 `tests/test_postgres_repos.py`（L2 仓储 CRUD 测试，39 个）

需要 PostgreSQL 服务，整体标记 `@pytest.mark.postgres`。

| 测试类 | 测试数 | 覆盖点 |
|--------|-------|--------|
| `TestPostgresTaskRepository` | 8 | save/find_by_id/upsert/find_by_demander/find_by_status(含 domain 过滤)/update_status(含不存在抛 KeyError) |
| `TestPostgresResourceRepository` | 6 | save/find_by_id/find_by_supplier/find_available(domain+IDLE)/update_status(含不存在抛 KeyError) |
| `TestPostgresDealRepository` | 3 | save/find_by_id/find_by_task/find_by_supplier |
| `TestPostgresUserRepository` | 3 | save/find_by_id/find_by_name/find_by_id_nonexistent |
| `TestPostgresTrustRepository` | 6 | save_and_find_by_domain/domain_isolation(同用户不同 domain 隔离)/find_by_domain_nonexistent/find_profile_returns_any(向后兼容)/save_and_find_evaluations/find_evaluations_empty |
| `TestPostgresEventRepository` | 4 | append_and_replay_all/replay_by_aggregate_id/replay_empty/replay_preserves_payload |
| `TestPostgresRepositoryBundle` | 3 | bundle_provides_all_repos/transaction_context(原子提交)/transaction_rollback(异常回滚) |
| `TestUMCPServerPostgresIntegration` | 2 | use_postgres_repositories 注入所有仓储/dispose 释放连接池 |
| `TestPostgresListAll` | 4 | task/resource/deal 的 list_all + task_list_all_empty |

### 6.3 `tests/test_recovery.py`（L3 复合任务智能恢复测试，6 个）

模拟 server 重启后从 PostgreSQL 恢复未终态复合任务。

| 测试 | 验证点 | 对应实现 |
|------|--------|---------|
| `test_recover_draft_subtask` | DRAFT 子任务重新派发并完成；父任务随之完成 | `server.py:631-634` |
| `test_recover_skips_terminal_composite` | 已终态复合任务跳过（recovered=0） | `server.py:587-591` 过滤 |
| `test_recover_marks_in_progress_as_timeout` | IN_PROGRESS 子任务标记 `_pending_timeout`，不重新派发 | `server.py:639-643` |
| `test_recover_returns_empty_when_no_composites` | 无复合任务时返回全 0 统计 | `server.py:575-578` |
| `test_recover_multiple_composites` | 多个复合任务串行恢复（recovered=3, redispatched=3） | `server.py:593-595` |
| `test_recover_completes_when_all_subtasks_terminal` | 恢复后所有子任务终态时父任务完成（无需派发） | `server.py:646-655` |

### 6.4 `tests/test_persistence_e2e.py`（L4 端到端持久化测试，5 个）

验证完整的启动→执行→重启→恢复→继续流程。逐方法标记 `@pytest.mark.postgres`，使 `test_in_memory_path_unaffected` 不被跳过。

| 测试 | 验证点 |
|------|--------|
| `test_task_persists_across_restart` | 任务在"重启"（新 server 实例同 PG）后仍可查询 |
| `test_composite_recovers_and_continues` | 复合任务在"重启"后恢复并继续执行至完成 |
| `test_event_log_persists` | 事件日志持久化并支持按聚合 ID 回放 |
| `test_transaction_atomicity` | `bundle.transaction()` 抛异常时回滚，数据未持久化 |
| `test_in_memory_path_unaffected` | InMemory 路径保持原行为（无 PG 依赖） |

### 6.5 测试覆盖总结

| 维度 | 覆盖情况 |
|------|---------|
| 转换器双向转换 | Task/Resource/Deal/User/TrustProfile/Evaluation/Event/Dependencies 全覆盖（12 个） |
| 仓储 CRUD | 6 个仓储 + Bundle 事务 + Server 集成 + list_all 全覆盖（39 个） |
| domain 隔离 | `test_domain_isolation` 验证同用户不同 domain 信任档案隔离 |
| 复合任务恢复 | DRAFT 重派/IN_PROGRESS 标记/全终态完成/多任务串行/空场景 全覆盖（6 个） |
| 端到端持久化 | 重启恢复/事件回放/事务原子性/InMemory 兼容 全覆盖（5 个） |
| PG 不可用容错 | `conftest.py` 自动 skip 机制 |
| 向后兼容 | `test_in_memory_path_unaffected` + `test_find_profile_returns_any` |

---

## 七、已知限制

1. **无读写分离**：当前所有读写都走主库，未实现读写分离。高并发读场景需后续扩展从库读 + 主库写。
2. **无分库分表**：单库单表，未实现按 domain 或 user_id 分片。超大规模数据量需后续引入分库分表方案。
3. **事件日志仅 append**：`events` 表只支持追加（`append`）与顺序回放（`replay`），不支持修改与删除。事件日志是审计用，**非事件溯源**——状态由业务表重建，events 表只用于追溯，不用于状态重建。
4. **复合任务恢复的部分场景待补全**：ASSIGNED/IN_PROGRESS 子任务仅标记 `_pending_timeout`，真正的超时取消机制在阶段五 D 实现（`server.py:640-643`）。
5. **SQLite 不支持 JSONB 索引**：本阶段仅支持 PostgreSQL（JSONB 是 PostgreSQL 原生类型）。SQLite 支持可后续扩展。
6. **单机部署**：水平扩展能力（多实例共享 PG + 分布式锁）在后续阶段实现。
7. **User 抽象类的通用兜底**：`user_from_orm` 用 `_GenericUser` 兜底重建，`authenticate` 恒返回 `True`。实际应用若需保留认证逻辑，应注册 `user_type → cls` 映射重建具体子类（见 `converters.py:232-269` 注释）。
