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
from pathlib import Path
from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.events.bus import EventBus, Event
from umcp_core.events.types import EventType
from umcp_core.layers.l1 import AuthProvider, PhoneAuthProvider
from umcp_core.layers.l2 import DefaultTaskFactory, ResourceRegistry
from umcp_core.layers.l3 import MatchStrategy
from umcp_core.layers.l4 import PaymentSchema
from umcp_core.layers.l5 import TrustEngine
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

        # 已加载插件
        self._plugins: list[PluginDescriptor] = []
        self._started: bool = False

        # 注册全局事件审计
        self.event_bus.subscribe_all(self._audit_event)

    # ------------------------------------------------------------------
    # 仓储配置
    # ------------------------------------------------------------------

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
        """按 domain 注册信任引擎，同时更新单值属性作为兜底。"""
        self._trust_engines[domain.lower()] = engine
        self.trust_engine = engine

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

        # 注入信任引擎
        if "trust_engine" in manifest:
            cls = _import_class(manifest["trust_engine"])
            instance = cls()
            self.trust_engine = instance
            for d in domains:
                self._trust_engines[d] = instance

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
    # 启动与停止
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动协议栈。"""
        if self._started:
            print("[UMCPServer] 已在运行中", file=sys.stderr)
            return
        self._validate_required_components()
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


def _import_class(dotted_path: str) -> type:
    """根据点分路径导入类。"""
    if "." not in dotted_path:
        raise ValueError(f"无效的点分路径: {dotted_path}")
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    if not hasattr(module, class_name):
        raise AttributeError(f"模块 {module_path} 中未找到类 {class_name}")
    return getattr(module, class_name)
