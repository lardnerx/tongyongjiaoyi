"""UMCPServer：协议栈启动入口与组件编排。

行业应用通过 UMCPServer 加载插件、注入 Repository 实现、启动协议栈。
核心库启动时扫描插件目录，根据 plugin.json 反射加载实现类，
并注入到协议栈的对应层。

用法示例：
    server = UMCPServer()
    server.use_in_memory_repositories()  # 开发调试用内存仓储
    server.load_plugin("plugins/ride_hailing/plugin.json")
    server.start()
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import Task, TaskStatus
from umcp_core.events.bus import EventBus, Event
from umcp_core.events.types import EventType
from umcp_core.layers.l1 import AuthProvider, PhoneAuthProvider
from umcp_core.layers.l2 import DefaultTaskFactory, ResourceRegistry
from umcp_core.layers.l3 import MatchStrategy
from umcp_core.layers.l4 import PaymentSchema
from umcp_core.layers.l5 import MeanTrustAggregator, TrustAggregator, TrustEngine
from umcp_core.layers.l6 import IntelligenceModule, NoopIntelligenceModule
from umcp_core.layers.l7 import RuleEngine
from umcp_core.repositories.in_memory import (
    InMemoryDealRepository,
    InMemoryEventRepository,
    InMemoryRepositoryBundle,
    InMemoryResourceRepository,
    InMemoryTaskRepository,
    InMemoryTrustRepository,
    InMemoryUserRepository,
)
from umcp_core.repositories.interfaces import (
    DealRepository,
    EventRepository,
    ResourceRepository,
    TaskRepository,
    TrustRepository,
    UserRepository,
)
from umcp_core.repositories.postgres.bundle import PostgresRepositoryBundle
from umcp_core.repositories.postgres.converters import task_to_orm
from umcp_core.repositories.postgres.models import CompositeDependencyModel


class PluginDescriptor:
    """已加载插件的描述信息。"""

    def __init__(self, manifest: dict[str, Any], path: Path) -> None:
        self.manifest: dict[str, Any] = manifest
        self.path: Path = path
        self.name: str = manifest.get("name", "unknown")
        self.version: str = manifest.get("version", "0.0.0")

    def __repr__(self) -> str:
        return f"<Plugin {self.name}@{self.version}>"


class UMCPServer:
    """UMCP 协议栈服务器。

    负责：
    - 管理各层组件的注入与生命周期
    - 加载行业插件（根据 plugin.json 反射注册实现类）
    - 提供统一的协议栈启动入口
    """

    def __init__(self) -> None:
        # 横切组件
        self.event_bus: EventBus = EventBus()
        self.rule_engine: RuleEngine = RuleEngine()

        # 各层组件（默认值）
        self.auth_provider: AuthProvider = PhoneAuthProvider()
        self.task_factory: DefaultTaskFactory = DefaultTaskFactory()
        self.resource_registry: ResourceRegistry | None = None
        self.match_strategy: MatchStrategy | None = None
        self.payment_schema: PaymentSchema | None = None
        self.trust_engine: TrustEngine | None = None
        self.intelligence_module: IntelligenceModule = NoopIntelligenceModule()

        # 仓储（默认 None，由 use_in_memory_repositories 或显式注入）
        self.task_repo: TaskRepository | None = None
        self.resource_repo: ResourceRepository | None = None
        self.deal_repo: DealRepository | None = None
        self.user_repo: UserRepository | None = None
        self.trust_repo: TrustRepository | None = None
        self.event_repo: EventRepository | None = None

        # 按 domain 索引的策略注册表（多插件并存支持）
        self._match_strategies: dict[str, MatchStrategy] = {}
        self._payment_schemas: dict[str, PaymentSchema] = {}
        self._trust_engines: dict[str, TrustEngine] = {}

        # 跨 domain 信任聚合器（默认算术平均）
        self._trust_aggregator: TrustAggregator = MeanTrustAggregator()

        # 复合任务子任务执行器（按 domain 注册，覆盖默认行为）
        self._subtask_executors: dict[str, Any] = {}

        # 已加载插件
        self._plugins: list[PluginDescriptor] = []
        self._started: bool = False

        # 注册全局事件审计
        self.event_bus.subscribe_all(self._audit_event)

    # ------------------------------------------------------------------
    # 仓储配置
    # ------------------------------------------------------------------

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

    def use_in_memory_repositories(self) -> InMemoryRepositoryBundle:
        """使用内存仓储（开发调试）。"""
        bundle = InMemoryRepositoryBundle()
        self.task_repo = bundle.task_repo
        self.resource_repo = bundle.resource_repo
        self.deal_repo = bundle.deal_repo
        self.user_repo = bundle.user_repo
        self.trust_repo = bundle.trust_repo
        self.event_repo = bundle.event_repo
        # 同步把 event_bus 的事件落库
        self.event_bus.subscribe_all(self.event_repo.append)
        return bundle

    def set_repositories(
        self,
        task_repo: TaskRepository,
        resource_repo: ResourceRepository,
        deal_repo: DealRepository,
        user_repo: UserRepository,
        trust_repo: TrustRepository,
        event_repo: EventRepository,
    ) -> None:
        """注入自定义仓储实现（生产环境）。"""
        self.task_repo = task_repo
        self.resource_repo = resource_repo
        self.deal_repo = deal_repo
        self.user_repo = user_repo
        self.trust_repo = trust_repo
        self.event_repo = event_repo
        self.event_bus.subscribe_all(self.event_repo.append)

    # ------------------------------------------------------------------
    # 层组件注入
    # ------------------------------------------------------------------

    def set_auth_provider(self, provider: AuthProvider) -> None:
        self.auth_provider = provider

    def set_match_strategy(self, strategy: MatchStrategy) -> None:
        self.match_strategy = strategy

    def set_payment_schema(self, schema: PaymentSchema) -> None:
        self.payment_schema = schema

    def set_trust_engine(self, engine: TrustEngine) -> None:
        self.trust_engine = engine

    def set_intelligence_module(self, module: IntelligenceModule) -> None:
        self.intelligence_module = module

    def set_resource_registry(self, registry: ResourceRegistry) -> None:
        self.resource_registry = registry

    # ------------------------------------------------------------------
    # 按 domain 注册的策略（多插件并存）
    # ------------------------------------------------------------------

    def register_match_strategy(self, domain: str, strategy: MatchStrategy) -> None:
        """按 domain 注册匹配策略，同时更新单值属性作为兜底。"""
        self._match_strategies[domain.lower()] = strategy
        self.match_strategy = strategy

    def register_payment_schema(self, domain: str, schema: PaymentSchema) -> None:
        """按 domain 注册支付模式，同时更新单值属性作为兜底。"""
        self._payment_schemas[domain.lower()] = schema
        self.payment_schema = schema

    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None:
        """按 domain 注册信任引擎。

        同时：
        - 更新单值属性 self.trust_engine（兜底）
        - 注册到 self._trust_engines[domain]
        - 同步到 self.rule_engine（供 RuleContext.trust_score 路由）
        """
        key = domain.lower()
        self._trust_engines[key] = engine
        self.trust_engine = engine
        # 同步到 RuleEngine，使 access_rule 的 trustScore 能按 domain 路由
        self.rule_engine.register_trust_engine(key, engine)

    def match_strategy_for(self, domain: DomainTag | str) -> MatchStrategy | None:
        """按 domain 查询匹配策略，未命中时回退到单值属性。"""
        key = domain.value if isinstance(domain, DomainTag) else str(domain).lower()
        return self._match_strategies.get(key, self.match_strategy)

    def payment_schema_for(self, domain: DomainTag | str) -> PaymentSchema | None:
        """按 domain 查询支付模式，未命中时回退到单值属性。"""
        key = domain.value if isinstance(domain, DomainTag) else str(domain).lower()
        return self._payment_schemas.get(key, self.payment_schema)

    def trust_engine_for(self, domain: DomainTag | str) -> TrustEngine | None:
        """按 domain 查询信任引擎，未命中时回退到单值属性。"""
        key = domain.value if isinstance(domain, DomainTag) else str(domain).lower()
        return self._trust_engines.get(key, self.trust_engine)

    def set_trust_aggregator(self, aggregator: TrustAggregator) -> None:
        """注入自定义信任聚合策略（默认 MeanTrustAggregator）。"""
        self._trust_aggregator = aggregator

    def aggregate_trust_score(self, user_id: str) -> float:
        """跨 domain 聚合 trust_score。

        返回所有已注册 domain 的 TrustEngine.evaluate(user_id).overall_score
        的聚合结果（默认算术平均，可通过 set_trust_aggregator 自定义）。
        """
        return self._trust_aggregator.aggregate(user_id, self._trust_engines)

    # ------------------------------------------------------------------
    # 任务工厂注册
    # ------------------------------------------------------------------

    def register_task_type(self, task_type: str, builder: Any) -> None:
        """注册任务类型到工厂。"""
        self.task_factory.register_builder(task_type, builder)

    # ------------------------------------------------------------------
    # 插件加载
    # ------------------------------------------------------------------

    def load_plugin(self, plugin_path: str | Path) -> PluginDescriptor:
        """加载行业插件。

        plugin_path 可以是：
        - plugin.json 文件路径
        - 包含 plugin.json 的目录
        - Python 模块路径（如 "ride_hailing"）
        """
        path = Path(plugin_path)
        if path.is_dir():
            manifest_path = path / "plugin.json"
        elif path.is_file() and path.suffix == ".json":
            manifest_path = path
        elif isinstance(plugin_path, str) and "/" not in plugin_path and "\\" not in plugin_path:
            # 当作 Python 模块名处理
            return self._load_plugin_module(plugin_path)
        else:
            raise FileNotFoundError(f"无法定位插件: {plugin_path}")

        if not manifest_path.exists():
            raise FileNotFoundError(f"插件描述文件不存在: {manifest_path}")

        with manifest_path.open(encoding="utf-8") as f:
            manifest = json.load(f)

        descriptor = PluginDescriptor(manifest, manifest_path)
        self._apply_manifest(descriptor)
        self._plugins.append(descriptor)
        return descriptor

    def _load_plugin_module(self, module_name: str) -> PluginDescriptor:
        """通过 Python 模块名加载插件。"""
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            raise ImportError(f"无法导入插件模块 {module_name}: {e}") from e

        if not hasattr(module, "PLUGIN_MANIFEST"):
            raise AttributeError(f"插件模块 {module_name} 缺少 PLUGIN_MANIFEST")
        manifest = getattr(module, "PLUGIN_MANIFEST")
        descriptor = PluginDescriptor(manifest, Path(module_name))
        self._apply_manifest(descriptor)
        # 允许插件模块自定义初始化钩子
        if hasattr(module, "register_plugin"):
            getattr(module, "register_plugin")(self)
        self._plugins.append(descriptor)
        return descriptor

    def _apply_manifest(self, descriptor: PluginDescriptor) -> None:
        """根据 plugin.json 反射加载实现类并注入。"""
        manifest = descriptor.manifest

        # 解析 domain（支持字符串或字符串列表，None 时退化为单值模式）
        # 统一小写化以与 DomainTag.of() 和 task.domain_tag.value 保持一致
        domain_field = manifest.get("domain")
        if domain_field is None:
            domains: list[str] = []
        elif isinstance(domain_field, str):
            domains = [domain_field.lower()]
        else:
            domains = [str(d).lower() for d in domain_field]

        # 注册任务类型
        for task_type_path in manifest.get("task_types", []):
            cls = _import_class(task_type_path)
            type_name = getattr(cls, "_task_type_name", cls.__name__.lower())
            self.task_factory.register_builder(type_name, cls)

        # 注入匹配策略
        if "match_strategy" in manifest:
            cls = _import_class(manifest["match_strategy"])
            instance = cls()
            self.match_strategy = instance
            for d in domains:
                self._match_strategies[d] = instance

        # 注入支付模式
        if "payment_schema" in manifest:
            cls = _import_class(manifest["payment_schema"])
            instance = cls()
            self.payment_schema = instance
            for d in domains:
                self._payment_schemas[d] = instance

        # 注入信任引擎（通过 register_trust_engine 同步到 RuleEngine）
        if "trust_engine" in manifest:
            cls = _import_class(manifest["trust_engine"])
            instance = cls()
            if domains:
                for d in domains:
                    self.register_trust_engine(d, instance)
            else:
                # 无 domain 时仅更新单值属性（保持原行为）
                self.trust_engine = instance

        # 配置准入规则（按 domain 注册，无 domain 时全局生效）
        if "access_rule_expression" in manifest:
            from umcp_core.layers.l7 import ExpressionAccessRule

            rule = ExpressionAccessRule(manifest["access_rule_expression"])
            if domains:
                for d in domains:
                    self.rule_engine.add_access_rule(rule, domain=d)
            else:
                self.rule_engine.add_access_rule(rule)

    # ------------------------------------------------------------------
    # 复合任务编排
    # ------------------------------------------------------------------

    def execute_composite(self, composite: CompositeTask) -> None:
        """驱动复合任务执行。

        流程：
        1. 绑定 EventBus（订阅子任务事件）
        2. 发布父任务 → 进入 MATCHING
        3. 注册 TASK_COMPLETED → SUBTASK_* 桥接
        4. 按 DAG 拓扑序启动就绪子任务
        5. 子任务完成事件触发父任务状态转移（由 CompositeTask 事件回调处理）

        本方法只负责"启动"，不负责"完成判定"——完成判定由事件驱动。
        """
        from umcp_core.core.composite_task import CompositeTask
        from umcp_core.core.task import TaskStatus

        if not isinstance(composite, CompositeTask):
            raise TypeError(f"期望 CompositeTask，收到 {type(composite).__name__}")
        if composite.status != TaskStatus.DRAFT:
            raise RuntimeError(f"复合任务状态 {composite.status} 不允许执行")

        # 0. 原子持久化父任务和子任务
        self._persist_composite_atomic(composite)

        # 1. 绑定 EventBus（触发 subscribe 子任务事件）
        composite.bind_event_bus(self.event_bus)

        # 2. 发布父任务
        composite.publish()

        # 3. 注册子任务事件桥接：TASK_COMPLETED → SUBTASK_*
        subtask_ids = {s.task_id for s in composite.subtasks}

        def _bridge_to_subtask_event(event: Event) -> None:
            task_id = event.payload.get("task_id")
            if task_id not in subtask_ids:
                return
            subtask = composite._find_sub(task_id)
            if event.payload.get("cancelled"):
                composite.emit_subtask_event(subtask, EventType.SUBTASK_CANCELLED)
            else:
                composite.emit_subtask_event(subtask, EventType.SUBTASK_COMPLETED)
            # 子任务状态变更后，尝试派发新就绪的子任务（串行依赖链推进）
            self._dispatch_ready_subtasks(composite)
            # 复合任务到达终态后取消订阅，避免桥接函数闭包泄漏
            if TaskStatus.is_terminal(composite.status):
                self.event_bus.unsubscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)

        self.event_bus.subscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)

        # 4. 启动所有就绪子任务
        self._dispatch_ready_subtasks(composite)

    def publish_and_match(self, task: Task) -> None:
        """发布并匹配单任务（HTTP 层入口）。

        - 标准任务：publish → 匹配 → assign → start_execution → complete
        - 复合任务：委托 execute_composite
        - 无匹配：cancel

        Args:
            task: 待发布的任务（必须 DRAFT 状态）

        Raises:
            RuntimeError: domain 未注册匹配策略，或 resource_repo 未注入
        """
        from umcp_core.core.composite_task import CompositeTask

        if isinstance(task, CompositeTask):
            self.execute_composite(task)
            return

        domain = task.domain_tag.value
        strategy = self.match_strategy_for(domain)
        if strategy is None:
            raise RuntimeError(f"domain {domain} 未注册匹配策略")
        if self.resource_repo is None:
            raise RuntimeError("resource_repo 未注入")

        # 持久化（若启用 PG）
        self.task_repo.save(task)

        task.bind_event_bus(self.event_bus)
        task.publish()
        candidates = self.resource_repo.find_available(task.domain_tag)
        result = strategy.execute(task, candidates)
        if not result.matched:
            task.cancel()
            return
        task.assign_to(result.selected_resource_id)
        task.start_execution()
        task.complete()
        self.task_repo.save(task)

    def _dispatch_ready_subtasks(self, composite: CompositeTask) -> None:
        """派发就绪子任务到对应 domain执行。

        仅绑定 EventBus，publish 时机交给 _execute_subtask_by_domain
        或自定义执行器（避免双重 publish 与 DRAFT→MATCHING 后再 publish 的非法转移）。

        注意：ready_subtasks() 返回的列表在迭代期间可能因 EventBus 同步 publish
        触发的递归调用而被"污染"（子任务状态变更），需在派发前重新校验 DRAFT 状态。
        """
        for subtask in composite.ready_subtasks():
            if subtask.status != TaskStatus.DRAFT:
                continue  # 可能在递归派发中已被推进
            subtask.bind_event_bus(self.event_bus)
            self._execute_subtask_by_domain(subtask)

    def _execute_subtask_by_domain(self, subtask: Task) -> None:
        """按子任务 domain_tag 路由到对应插件的匹配策略执行。"""
        domain = subtask.domain_tag.value
        custom_executor = self._subtask_executors.get(domain)
        if custom_executor is not None:
            custom_executor(subtask)
            return

        strategy = self.match_strategy_for(domain)
        if strategy is None:
            raise RuntimeError(f"domain {domain} 未注册匹配策略")
        if self.resource_repo is None:
            raise RuntimeError("resource_repo 未注入")

        # 默认执行器负责把子任务从 DRAFT 推进到终态：
        # publish → assign_to → start_execution → complete
        subtask.publish()
        candidates = self.resource_repo.find_available(subtask.domain_tag)
        result = strategy.execute(subtask, candidates)
        if not result.matched:
            subtask.cancel()
            return

        subtask.assign_to(result.selected_resource_id)
        subtask.start_execution()
        subtask.complete()

    def register_subtask_executor(
        self, domain: str, executor: Any
    ) -> None:
        """注册特定 domain 的子任务执行器（覆盖默认 _execute_subtask_by_domain）。"""
        self._subtask_executors[domain.lower()] = executor

    # ------------------------------------------------------------------
    # 持久化与恢复
    # ------------------------------------------------------------------

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
        from umcp_core.core.composite_task import CompositeTask

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
            tasks = self.task_repo.find_by_status(status)
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

        # 重新注册 TASK_COMPLETED → SUBTASK_* 桥接（与 execute_composite 中的逻辑一致）
        subtask_ids = {s.task_id for s in composite.subtasks}

        def _bridge_to_subtask_event(event: Event) -> None:
            task_id = event.payload.get("task_id")
            if task_id not in subtask_ids:
                return
            subtask = composite._find_sub(task_id)
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

        # 遍历子任务，按状态分类处理
        for subtask in composite.subtasks:
            if TaskStatus.is_terminal(subtask.status):
                continue

            if subtask.status == TaskStatus.DRAFT:
                subtask.bind_event_bus(self.event_bus)
                self._execute_subtask_by_domain(subtask)
                stats["redispatched"] += 1
            elif subtask.status in (TaskStatus.MATCHING, TaskStatus.PUBLISHED):
                subtask.bind_event_bus(self.event_bus)
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

    # ------------------------------------------------------------------
    # 启动与停止
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动协议栈。"""
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

        print(
            f"[UMCPServer] 协议栈已启动。已加载插件: "
            f"{[p.name for p in self._plugins] or '<无>'}"
        )
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        print("[UMCPServer] 协议栈已停止")

    def _validate_required_components(self) -> None:
        """校验启动前必需组件是否就绪。"""
        missing: list[str] = []
        if self.match_strategy is None:
            missing.append("match_strategy")
        if self.payment_schema is None:
            missing.append("payment_schema")
        if self.trust_engine is None:
            missing.append("trust_engine")
        if self.task_repo is None:
            missing.append("task_repo (调用 use_in_memory_repositories 或 set_repositories)")
        if missing:
            raise RuntimeError(
                f"协议栈启动缺少必需组件: {missing}。"
                f"请通过 load_plugin 加载行业插件或手动注入。"
            )

    # ------------------------------------------------------------------
    # 审计
    # ------------------------------------------------------------------

    def _audit_event(self, event: Event) -> None:
        """全局事件审计钩子（L7 治理层）。"""
        # 默认仅打印到 stderr，生产环境可替换为结构化日志
        if event.type in (
            EventType.ANOMALY_DETECTED,
            EventType.RULE_TRIGGERED,
            EventType.DISPUTE_OPENED,
        ):
            print(f"[UMCPServer 审计] {event}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 内省
    # ------------------------------------------------------------------

    @property
    def plugins(self) -> list[PluginDescriptor]:
        return list(self._plugins)

    @property
    def is_running(self) -> bool:
        return self._started

    @property
    def trust_aggregator(self) -> TrustAggregator:
        """返回当前信任聚合器（供测试内省用）。"""
        return self._trust_aggregator


def _import_class(dotted_path: str) -> type:
    """根据点分路径导入类。"""
    if "." not in dotted_path:
        raise ValueError(f"无效的点分路径: {dotted_path}")
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    if not hasattr(module, class_name):
        raise AttributeError(f"模块 {module_path} 中未找到类 {class_name}")
    return getattr(module, class_name)
