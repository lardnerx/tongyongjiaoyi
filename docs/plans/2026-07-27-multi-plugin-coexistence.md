# 阶段四 A：多插件并存 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 UMCPServer 同时承载多个行业插件，按 DomainTag 路由到各自的 match_strategy / payment_schema / trust_engine / access_rules，互不覆盖。

**架构：** 在 server.py 新增按 domain 索引的注册表与 `*_for(domain)` 查询方法（保留单值属性作兜底）；在 governance.py 让 RuleEngine 按 `task.domain_tag` 路由 access_rules；三个插件 manifest 新增 `domain` 字段，`register_plugin` 钩子改用 `register_*`。

**技术栈：** Python 3.10+、pytest、无新增依赖

**规格：** `docs/specs/2026-07-27-multi-plugin-coexistence-design.md`

---

## 文件结构

**核心库改动（2 文件）：**
- `src/umcp_core/layers/l7/governance.py` — `RuleEngine` 新增 `_domain_access_rules` 字典与 `add_access_rule(rule, domain=None)` 签名；`check_access` 按 `task.domain_tag` 路由
- `src/umcp_core/server.py` — `UMCPServer` 新增三个 domain 注册表、`register_*` / `*_for` 方法；`_apply_manifest` 读取 `domain` 字段并按 domain 注册策略与 access_rule

**插件包改动（3 插件 × 2 文件 = 6 文件）：**
- `plugins/ride_hailing/plugin.json` + `__init__.py` — 加 `"domain": "ride"`，`register_plugin` 改用 `register_*`
- `plugins/escort_driving/plugin.json` + `__init__.py` — 加 `"domain": "escort"`，`register_plugin` 改用 `register_*`
- `plugins/group_buying/plugin.json` + `__init__.py` — 加 `"domain": "group_buying"`，`register_plugin` 改用 `register_*`

**测试（2 文件）：**
- `tests/test_multi_plugin_routing.py` — 新建，6 个单元测试覆盖注册表路由与 RuleEngine domain 隔离
- `tests/test_end_to_end_multi_plugin.py` — 新建，6 个端到端测试覆盖三插件并存场景

**Demo（1 文件）：**
- `examples/multi_plugin_demo.py` — 新建，在同一 UMCPServer 上跑通三 domain 完整流程

---

## 任务 1：RuleEngine 按 domain 路由

**文件：**
- 修改：`src/umcp_core/layers/l7/governance.py:153-185`（`RuleEngine` 类）
- 测试：`tests/test_multi_plugin_routing.py`（新建）

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_multi_plugin_routing.py`，先写 RuleEngine 部分的两个测试：

```python
"""多插件路由单元测试。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.core.base import User
from umcp_core.layers.l7 import ExpressionAccessRule, RuleEngine


def _make_user(credentials: list[str] | None = None, trust_score: float = 5.0) -> User:
    user = User(user_id="u1", phone="13800000000")
    user.metadata["credentials"] = credentials or []
    user.metadata["trust_score"] = trust_score
    return user


def _make_task(domain: str) -> CustomTask:
    return CustomTask(
        demander_id="u1",
        domain_tag=DomainTag.of(domain),
    )


def test_rule_engine_domain_scoped_access():
    """domain 范围的 access_rule 只对该 domain 生效。"""
    engine = RuleEngine()
    # ride domain 要求 driver_license
    engine.add_access_rule(
        ExpressionAccessRule("hasCredential('driver_license')"),
        domain="ride",
    )
    # group_buying domain 要求 business_license
    engine.add_access_rule(
        ExpressionAccessRule("hasCredential('business_license')"),
        domain="group_buying",
    )

    # ride task：用户有 driver_license 但无 business_license，应通过
    ride_user = _make_user(credentials=["driver_license"])
    ride_task = _make_task("ride")
    assert engine.check_access(ride_user, ride_task) is True

    # group_buying task：同一用户无 business_license，应拒绝
    gb_task = _make_task("group_buying")
    assert engine.check_access(ride_user, gb_task) is False


def test_rule_engine_global_fallback():
    """无 domain 参数的 access_rule 对所有 domain 生效。"""
    engine = RuleEngine()
    # 全局规则：trustScore >= 3.0
    engine.add_access_rule(ExpressionAccessRule("trustScore >= 3.0"))

    # 低信任用户在任何 domain 都应被拒绝
    low_trust_user = _make_user(trust_score=2.0)
    assert engine.check_access(low_trust_user, _make_task("ride")) is False
    assert engine.check_access(low_trust_user, _make_task("group_buying")) is False

    # 高信任用户在任何 domain 都应通过
    high_trust_user = _make_user(trust_score=5.0)
    assert engine.check_access(high_trust_user, _make_task("ride")) is True
    assert engine.check_access(high_trust_user, _make_task("group_buying")) is True
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_multi_plugin_routing.py::test_rule_engine_domain_scoped_access tests/test_multi_plugin_routing.py::test_rule_engine_global_fallback -v`
预期：FAIL，报错 `ExpressionAccessRule.__init__() got an unexpected keyword argument 'domain'` 或 `add_access_rule() got an unexpected keyword argument 'domain'`

- [ ] **步骤 3：实现 RuleEngine 改造**

修改 `src/umcp_core/layers/l7/governance.py` 的 `RuleEngine` 类（约 153-185 行）：

```python
class RuleEngine:
    """规则引擎：跨层规则注入总线。

    L7 是协议栈的"大脑皮层"和"宪法"，与其他所有层交叉，
    将各阶段积累的隐性治理规则抽象为可配置、可审计的元规则。

    支持按 domain 隔离 access_rules：domain-scoped 规则只对对应 domain 的 task 生效，
    全局规则（无 domain）对所有 task 生效。
    """

    def __init__(self) -> None:
        self._access_rules: list[AccessRule] = []  # 全局兜底
        self._domain_access_rules: dict[str, list[AccessRule]] = {}  # 按 domain
        self._arbitration_policy: ArbitrationPolicy = SimpleArbitrationPolicy()
        self._compliance: ComplianceModule = NoopComplianceModule()

    def add_access_rule(self, rule: AccessRule, domain: str | None = None) -> None:
        """注册准入规则。

        domain 为 None 时注册为全局规则（对所有 task 生效）；
        否则只对该 domain 的 task 生效。
        """
        if domain is None:
            self._access_rules.append(rule)
        else:
            self._domain_access_rules.setdefault(domain, []).append(rule)

    def set_arbitration_policy(self, policy: ArbitrationPolicy) -> None:
        self._arbitration_policy = policy

    def set_compliance_module(self, module: ComplianceModule) -> None:
        self._compliance = module

    def check_access(self, user: User, task: Task) -> bool:
        """检查所有准入规则。任一不通过则拒绝。

        优先校验 task.domain_tag 对应的 domain 规则，再校验全局规则。
        """
        domain = task.domain_tag.value
        rules = self._domain_access_rules.get(domain, []) + self._access_rules
        return all(rule.check(user, task) for rule in rules)

    def arbitrate(self, dispute: Dispute) -> ArbitrationResult:
        return self._arbitration_policy.arbitrate(dispute)

    def audit(self, deal: Deal) -> bool:
        return self._compliance.audit(deal)

    def get_required_compliances(self, task: Task) -> list[str]:
        return self._compliance.get_required_compliances(task)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_multi_plugin_routing.py::test_rule_engine_domain_scoped_access tests/test_multi_plugin_routing.py::test_rule_engine_global_fallback -v`
预期：PASS（2 个测试通过）

- [ ] **步骤 5：运行全量测试确认无回归**

运行：`python -m pytest -q`
预期：224 passed（与改造前一致，证明向后兼容）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/layers/l7/governance.py tests/test_multi_plugin_routing.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(l7): RuleEngine 支持 domain 隔离的 access_rule"
```

---

## 任务 2：UMCPServer 多策略注册表 + _apply_manifest 改造

**文件：**
- 修改：`src/umcp_core/server.py:64-100`（`UMCPServer.__init__`）、`server.py:219-254`（`_apply_manifest`）
- 测试：`tests/test_multi_plugin_routing.py`（追加 4 个测试）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_multi_plugin_routing.py` 末尾追加：

```python
from umcp_core.layers.l3 import InstantMatch, ReverseAuction
from umcp_core.layers.l4 import DynamicPricing, InstallmentPayment, FlatCommissionRule
from umcp_core.layers.l5 import WeightedSumTrustEngine
from umcp_core.server import UMCPServer


def test_register_match_strategy_by_domain():
    """register_match_strategy 按 domain 注册，*_for 按 domain 查询。"""
    server = UMCPServer()
    ride_strategy = InstantMatch()
    gb_strategy = ReverseAuction()

    server.register_match_strategy("ride", ride_strategy)
    server.register_match_strategy("group_buying", gb_strategy)

    assert server.match_strategy_for("ride") is ride_strategy
    assert server.match_strategy_for("group_buying") is gb_strategy
    # DomainTag 也能作为参数
    assert server.match_strategy_for(DomainTag.of("ride")) is ride_strategy


def test_match_strategy_for_falls_back_to_default():
    """未注册的 domain 回退到单值属性。"""
    server = UMCPServer()
    default_strategy = InstantMatch()
    server.set_match_strategy(default_strategy)

    # 未注册 domain 应回退到默认
    assert server.match_strategy_for("unknown_domain") is default_strategy
    # 单值属性本身也保留
    assert server.match_strategy is default_strategy


def test_payment_schema_routing():
    """payment_schema 按 domain 路由。"""
    server = UMCPServer()
    ride_pay = DynamicPricing(surge_factor=1.0, commission_rule=FlatCommissionRule(rate=0.20))
    gb_pay = InstallmentPayment(deposit_ratio=0.3, commission_rule=FlatCommissionRule(rate=0.05))

    server.register_payment_schema("ride", ride_pay)
    server.register_payment_schema("group_buying", gb_pay)

    assert server.payment_schema_for("ride") is ride_pay
    assert server.payment_schema_for("group_buying") is gb_pay


def test_trust_engine_routing():
    """trust_engine 按 domain 路由。"""
    server = UMCPServer()
    ride_engine = WeightedSumTrustEngine(dimensions=["punctuality", "cleanliness"])
    gb_engine = WeightedSumTrustEngine(dimensions=["delivery", "quality"])

    server.register_trust_engine("ride", ride_engine)
    server.register_trust_engine("group_buying", gb_engine)

    assert server.trust_engine_for("ride") is ride_engine
    assert server.trust_engine_for("group_buying") is gb_engine


def test_register_updates_single_value_property():
    """register_* 同时更新单值属性作为兜底（指向最后注册的）。"""
    server = UMCPServer()
    s1 = InstantMatch()
    s2 = ReverseAuction()

    server.register_match_strategy("ride", s1)
    assert server.match_strategy is s1  # 单值指向最后注册的

    server.register_match_strategy("group_buying", s2)
    assert server.match_strategy is s2  # 单值更新为最后注册的


def test_apply_manifest_registers_by_domain():
    """_apply_manifest 读取 domain 字段并按 domain 注册。"""
    server = UMCPServer()
    manifest = {
        "name": "test-plugin",
        "version": "1.0.0",
        "domain": "test_domain",
        "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
        "payment_schema": "umcp_core.layers.l4.DynamicPricing",
        "trust_engine": "umcp_core.layers.l5.WeightedSumTrustEngine",
        "access_rule_expression": "trustScore >= 3.0",
    }
    from umcp_core.server import PluginDescriptor
    from pathlib import Path
    descriptor = PluginDescriptor(manifest, Path("."))
    server._apply_manifest(descriptor)

    # 按 domain 应能查到对应策略
    assert server.match_strategy_for("test_domain") is not None
    assert isinstance(server.match_strategy_for("test_domain"), InstantMatch)
    # access_rule 也应注册到 test_domain
    gb_task = _make_task("test_domain")
    high_trust_user = _make_user(trust_score=5.0)
    assert server.rule_engine.check_access(high_trust_user, gb_task) is True


def test_apply_manifest_without_domain_falls_back_to_single_value():
    """缺 domain 字段时只更新单值属性，不注册到 domain 表（向后兼容）。"""
    server = UMCPServer()
    manifest = {
        "name": "legacy-plugin",
        "version": "1.0.0",
        "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    }
    from umcp_core.server import PluginDescriptor
    from pathlib import Path
    descriptor = PluginDescriptor(manifest, Path("."))
    server._apply_manifest(descriptor)

    # 单值属性应被设置
    assert isinstance(server.match_strategy, InstantMatch)
    # 但 domain 表应为空，*_for 查不到
    assert server.match_strategy_for("any_domain") is server.match_strategy  # 回退到默认
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_multi_plugin_routing.py -v`
预期：FAIL，新追加的测试报错 `AttributeError: 'UMCPServer' object has no attribute 'register_match_strategy'`

- [ ] **步骤 3：实现 UMCPServer 改造**

修改 `src/umcp_core/server.py`：

**3a. 在 `UMCPServer.__init__` 中添加注册表字段**（约 73-97 行，在 `self._plugins` 之前插入）：

```python
        # 按 domain 索引的策略注册表（多插件并存支持）
        self._match_strategies: dict[str, MatchStrategy] = {}
        self._payment_schemas: dict[str, PaymentSchema] = {}
        self._trust_engines: dict[str, TrustEngine] = {}

        # 已加载插件
        self._plugins: list[PluginDescriptor] = []
        self._started: bool = False
```

**3b. 在 `set_*` 方法之后添加 `register_*` 与 `*_for` 方法**（约 156 行 `set_resource_registry` 之后）：

```python
    # ------------------------------------------------------------------
    # 按 domain 注册的策略（多插件并存）
    # ------------------------------------------------------------------

    def register_match_strategy(self, domain: str, strategy: MatchStrategy) -> None:
        """按 domain 注册匹配策略，同时更新单值属性作为兜底。"""
        self._match_strategies[domain] = strategy
        self.match_strategy = strategy

    def register_payment_schema(self, domain: str, schema: PaymentSchema) -> None:
        """按 domain 注册支付模式，同时更新单值属性作为兜底。"""
        self._payment_schemas[domain] = schema
        self.payment_schema = schema

    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None:
        """按 domain 注册信任引擎，同时更新单值属性作为兜底。"""
        self._trust_engines[domain] = engine
        self.trust_engine = engine

    def match_strategy_for(self, domain: DomainTag | str) -> MatchStrategy | None:
        """按 domain 查询匹配策略，未命中时回退到单值属性。"""
        key = domain.value if isinstance(domain, DomainTag) else domain
        return self._match_strategies.get(key, self.match_strategy)

    def payment_schema_for(self, domain: DomainTag | str) -> PaymentSchema | None:
        """按 domain 查询支付模式，未命中时回退到单值属性。"""
        key = domain.value if isinstance(domain, DomainTag) else domain
        return self._payment_schemas.get(key, self.payment_schema)

    def trust_engine_for(self, domain: DomainTag | str) -> TrustEngine | None:
        """按 domain 查询信任引擎，未命中时回退到单值属性。"""
        key = domain.value if isinstance(domain, DomainTag) else domain
        return self._trust_engines.get(key, self.trust_engine)
```

**3c. 改造 `_apply_manifest`**（约 219-254 行）：

```python
    def _apply_manifest(self, descriptor: PluginDescriptor) -> None:
        """根据 plugin.json 反射加载实现类并注入。"""
        manifest = descriptor.manifest

        # 解析 domain（支持字符串或字符串列表，None 时退化为单值模式）
        domain_field = manifest.get("domain")
        if domain_field is None:
            domains: list[str] = []
        elif isinstance(domain_field, str):
            domains = [domain_field]
        else:
            domains = list(domain_field)

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
```

注意：原 `_apply_manifest` 中的 `match_strategy` / `payment_schema` / `trust_engine` 字段在旧 manifest 中并不存在（现有三个插件 manifest 都没有这三个字段，它们通过 `register_plugin` 钩子注入）。但保留这部分代码作为通用兜底——若未来有插件直接在 manifest 声明这些字段，仍能工作。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_multi_plugin_routing.py -v`
预期：PASS（8 个测试全部通过）

- [ ] **步骤 5：运行全量测试确认无回归**

运行：`python -m pytest -q`
预期：224 passed（与改造前一致）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/server.py tests/test_multi_plugin_routing.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(server): UMCPServer 支持按 domain 路由策略与 access_rule"
```

---

## 任务 3：三个插件 manifest 迁移

**文件：**
- 修改：`plugins/ride_hailing/plugin.json` + `plugins/ride_hailing/__init__.py`
- 修改：`plugins/escort_driving/plugin.json` + `plugins/escort_driving/__init__.py`
- 修改：`plugins/group_buying/plugin.json` + `plugins/group_buying/__init__.py`
- 测试：现有 `plugins/*/tests/test_plugin_loading.py`（零改动，验证兼容）

- [ ] **步骤 1：修改 ride_hailing 插件**

修改 `plugins/ride_hailing/plugin.json`，在 `"version"` 之后添加 `"domain": "ride"`：

```json
{
  "name": "ride-hailing",
  "version": "1.0.0",
  "domain": "ride",
  "task_types": ["ride_hailing.tasks.RideTask"],
  "resource_types": ["ride_hailing.resources.DriverResource"],
  "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
  "trust_dimensions": ["punctuality", "cleanliness", "driving_smoothness", "communication"],
  "commission_rate": 0.20,
  "access_rule_expression": "hasCredential('driver_license') && trustScore >= 4.0"
}
```

修改 `plugins/ride_hailing/__init__.py`：

(a) 在 `PLUGIN_MANIFEST` 字典中添加 `"domain": "ride"` 字段（放在 `"version"` 之后）：

```python
PLUGIN_MANIFEST = {
    "name": "ride-hailing",
    "version": "1.0.0",
    "domain": "ride",
    "task_types": ["ride_hailing.tasks.RideTask"],
    "resource_types": ["ride_hailing.resources.DriverResource"],
    "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    "trust_dimensions": ["punctuality", "cleanliness", "driving_smoothness", "communication"],
    "commission_rate": 0.20,
    "access_rule_expression": "hasCredential('driver_license') && trustScore >= 4.0",
}
```

(b) 修改 `register_plugin` 钩子，将 `server.set_*` 改为 `server.register_*(domain, ...)`：

```python
def register_plugin(server: "UMCPServer") -> None:
    """插件自定义初始化钩子。

    按 domain 注册策略组件，同时更新单值属性作为兜底。
    """
    domain = PLUGIN_MANIFEST["domain"]
    from umcp_core.layers.l3 import CredentialFilter, InstantMatch
    from umcp_core.layers.l4 import DynamicPricing, FlatCommissionRule
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from ride_hailing.scoring import RideMatchScorer

    server.register_match_strategy(
        domain,
        InstantMatch(
            scorer=RideMatchScorer(),
            filters=[CredentialFilter(required_credentials=["driver_license"])],
        ),
    )
    server.register_payment_schema(
        domain,
        DynamicPricing(
            surge_factor=1.0,
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        ),
    )
    server.register_trust_engine(
        domain,
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"]),
    )
```

- [ ] **步骤 2：修改 escort_driving 插件**

修改 `plugins/escort_driving/plugin.json`，添加 `"domain": "escort"`：

```json
{
  "name": "escort-driving",
  "version": "1.0.0",
  "domain": "escort",
  "task_types": ["escort_driving.tasks.EscortTask"],
  "resource_types": ["escort_driving.resources.CoachResource"],
  "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
  "trust_dimensions": ["teaching_ability", "patience", "safety_record"],
  "commission_rate": 0.20,
  "hourly_rate": 80.0,
  "access_rule_expression": "hasCredential('coach_license') && trustScore >= 4.0"
}
```

修改 `plugins/escort_driving/__init__.py`：

(a) `PLUGIN_MANIFEST` 添加 `"domain": "escort"`：

```python
PLUGIN_MANIFEST = {
    "name": "escort-driving",
    "version": "1.0.0",
    "domain": "escort",
    "task_types": ["escort_driving.tasks.EscortTask"],
    "resource_types": ["escort_driving.resources.CoachResource"],
    "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    "trust_dimensions": ["teaching_ability", "patience", "safety_record"],
    "commission_rate": 0.20,
    "hourly_rate": 80.0,
    "access_rule_expression": "hasCredential('coach_license') && trustScore >= 4.0",
}
```

(b) `register_plugin` 改为 `register_*`：

```python
def register_plugin(server: "UMCPServer") -> None:
    """插件自定义初始化钩子。

    按 domain 注册策略组件，同时更新单值属性作为兜底。
    """
    domain = PLUGIN_MANIFEST["domain"]
    from umcp_core.layers.l3 import CredentialFilter, InstantMatch
    from umcp_core.layers.l4 import FlatCommissionRule, Hourly
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from escort_driving.scoring import EscortMatchScorer

    server.register_match_strategy(
        domain,
        InstantMatch(
            scorer=EscortMatchScorer(),
            filters=[CredentialFilter(required_credentials=["coach_license"])],
        ),
    )
    server.register_payment_schema(
        domain,
        Hourly(
            hourly_rate=PLUGIN_MANIFEST["hourly_rate"],
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        ),
    )
    server.register_trust_engine(
        domain,
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"]),
    )
```

- [ ] **步骤 3：修改 group_buying 插件**

修改 `plugins/group_buying/plugin.json`，添加 `"domain": "group_buying"`：

```json
{
  "name": "group-buying",
  "version": "1.0.0",
  "domain": "group_buying",
  "task_types": [
    "group_buying.tasks.BuyerTask",
    "group_buying.tasks.TenderTask"
  ],
  "resource_types": ["group_buying.resources.SupplierResource"],
  "match_strategy": "umcp_core.layers.l3.matching.ReverseAuction",
  "trust_dimensions": ["delivery", "quality", "service", "cost_performance"],
  "commission_rate": 0.05,
  "deposit_ratio": 0.3,
  "access_rule_expression": "hasCredential('business_license') && trustScore >= 3.0"
}
```

修改 `plugins/group_buying/__init__.py`：

(a) `PLUGIN_MANIFEST` 添加 `"domain": "group_buying"`：

```python
PLUGIN_MANIFEST = {
    "name": "group-buying",
    "version": "1.0.0",
    "domain": "group_buying",
    "task_types": [
        "group_buying.tasks.BuyerTask",
        "group_buying.tasks.TenderTask",
    ],
    "resource_types": ["group_buying.resources.SupplierResource"],
    "match_strategy": "umcp_core.layers.l3.matching.ReverseAuction",
    "trust_dimensions": ["delivery", "quality", "service", "cost_performance"],
    "commission_rate": 0.05,
    "deposit_ratio": 0.3,
    "access_rule_expression": "hasCredential('business_license') && trustScore >= 3.0",
}
```

(b) `register_plugin` 改为 `register_*`：

```python
def register_plugin(server: "UMCPServer") -> None:
    """插件自定义初始化钩子。

    按 domain 注册策略组件，同时更新单值属性作为兜底。
    """
    domain = PLUGIN_MANIFEST["domain"]
    from umcp_core.layers.l3 import CredentialFilter, ReverseAuction
    from umcp_core.layers.l4 import FlatCommissionRule, InstallmentPayment
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from group_buying.scoring import TenderBidScorer

    server.register_match_strategy(
        domain,
        ReverseAuction(
            scorer=TenderBidScorer(),
            filters=[CredentialFilter(required_credentials=["business_license"])],
        ),
    )
    server.register_payment_schema(
        domain,
        InstallmentPayment(
            deposit_ratio=PLUGIN_MANIFEST["deposit_ratio"],
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        ),
    )
    server.register_trust_engine(
        domain,
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"]),
    )
```

- [ ] **步骤 4：运行三个插件的加载测试验证零回归**

运行：`python -m pytest plugins/ride_hailing/tests/test_plugin_loading.py plugins/escort_driving/tests/test_plugin_loading.py plugins/group_buying/tests/test_plugin_loading.py -v`
预期：所有现有插件加载测试 PASS（零改动通过，证明 X2 兼容性）

- [ ] **步骤 5：运行全量测试确认无回归**

运行：`python -m pytest -q`
预期：224 passed

- [ ] **步骤 6：Commit**

```bash
git add plugins/ride_hailing/plugin.json plugins/ride_hailing/__init__.py plugins/escort_driving/plugin.json plugins/escort_driving/__init__.py plugins/group_buying/plugin.json plugins/group_buying/__init__.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(plugins): 三个插件 manifest 添加 domain 字段并改用 register_*"
```

---

## 任务 4：端到端测试 - 多插件并存

**文件：**
- 测试：`tests/test_end_to_end_multi_plugin.py`（新建）

- [ ] **步骤 1：编写测试文件**

新建 `tests/test_end_to_end_multi_plugin.py`：

```python
"""多插件并存端到端测试：同一 UMCPServer 同时加载三个插件，按 domain 各自走通完整流程。"""
from __future__ import annotations

import pytest

from umcp_core.core import DomainTag
from umcp_core.core.domain import Credential
from umcp_core.server import UMCPServer


@pytest.fixture
def server() -> UMCPServer:
    """加载三个插件的 server。"""
    s = UMCPServer()
    s.use_in_memory_repositories()
    s.load_plugin("ride_hailing")
    s.load_plugin("escort_driving")
    s.load_plugin("group_buying")
    s.start()
    return s


def test_load_three_plugins_simultaneously(server: UMCPServer):
    """同一 server 加载 3 个插件，无报错。"""
    assert len(server.plugins) == 3
    names = [p.name for p in server.plugins]
    assert "ride-hailing" in names
    assert "escort-driving" in names
    assert "group-buying" in names


def test_each_domain_uses_own_strategy(server: UMCPServer):
    """ride 用 InstantMatch，group_buying 用 ReverseAuction。"""
    from umcp_core.layers.l3 import InstantMatch, ReverseAuction

    ride_strategy = server.match_strategy_for("ride")
    gb_strategy = server.match_strategy_for("group_buying")
    escort_strategy = server.match_strategy_for("escort")

    assert isinstance(ride_strategy, InstantMatch)
    assert isinstance(gb_strategy, ReverseAuction)
    assert isinstance(escort_strategy, InstantMatch)
    # 三个策略应是不同实例
    assert ride_strategy is not gb_strategy
    assert ride_strategy is not escort_strategy


def test_each_domain_uses_own_payment(server: UMCPServer):
    """ride 走 DynamicPricing（20% 抽成），group_buying 走 InstallmentPayment（5% + 30% 订金）。"""
    from umcp_core.layers.l4 import DynamicPricing, InstallmentPayment

    ride_pay = server.payment_schema_for("ride")
    gb_pay = server.payment_schema_for("group_buying")

    assert isinstance(ride_pay, DynamicPricing)
    assert isinstance(gb_pay, InstallmentPayment)
    assert gb_pay.deposit_ratio == 0.3
    # ride_pay 的 commission_rule rate 应为 0.20
    assert ride_pay.commission_rule.rate == 0.20
    # gb_pay 的 commission_rule rate 应为 0.05
    assert gb_pay.commission_rule.rate == 0.05


def test_each_domain_uses_own_trust_dimensions(server: UMCPServer):
    """ride 与 group_buying 评价维度独立。"""
    ride_engine = server.trust_engine_for("ride")
    gb_engine = server.trust_engine_for("group_buying")

    # WeightedSumTrustEngine 内部维护 dimensions 配置
    assert ride_engine is not gb_engine
    # 通过实际记录评价验证维度独立
    from umcp_core.layers.l5 import Evaluation

    ride_eval = Evaluation(
        evaluator_id="buyer_1",
        evaluatee_id="driver_1",
        task_id="task_1",
        ratings={"punctuality": 5.0, "cleanliness": 4.0,
                 "driving_smoothness": 5.0, "communication": 4.0},
    )
    server.trust_engine_for("ride").record_evaluation(ride_eval)
    ride_profile = server.trust_engine_for("ride").evaluate("driver_1")
    assert ride_profile.get_score("punctuality") == 5.0

    # group_buying 的 driver_1 评价应为空（隔离）
    gb_profile = server.trust_engine_for("group_buying").evaluate("driver_1")
    assert gb_profile.get_score("punctuality") == 0.0


def test_access_rule_does_not_leak_across_domains(server: UMCPServer):
    """ride 的 driver_license 要求不卡 group_buying 买家。"""
    from umcp_core.core.base import User

    # 用户只有 business_license，无 driver_license
    gb_user = User(user_id="gb_buyer", phone="13800000001")
    gb_user.metadata["credentials"] = ["business_license"]
    gb_user.metadata["trust_score"] = 5.0

    # ride task：缺 driver_license，应拒绝
    ride_task = _make_task("ride")
    assert server.rule_engine.check_access(gb_user, ride_task) is False

    # group_buying task：有 business_license，应通过
    gb_task = _make_task("group_buying")
    assert server.rule_engine.check_access(gb_user, gb_task) is True


def test_three_full_flows_in_one_server(server: UMCPServer):
    """同一 server 内串行执行三个完整交易流程，互不串扰。

    简化验证：每个 domain 各发起一次匹配，确认走对策略且无异常。
    完整支付/评价流程由单插件端到端测试覆盖，此处聚焦路由正确性。
    """
    from umcp_core.core import ResourceStatus
    from umcp_core.core.task import CustomTask
    from ride_hailing.resources import DriverResource
    from ride_hailing.tasks import RideTask

    # === ride 流程 ===
    driver = DriverResource(
        supplier_id="s_ride",
        domain_tag=DomainTag.of("ride"),
        current_lat=39.905,
        current_lng=116.408,
    )
    driver.register()
    server.resource_repo.save(driver)

    ride_task = RideTask(
        demander_id="d_ride",
        domain_tag=DomainTag.of("ride"),
        origin_lat=39.9042,
        origin_lng=116.4074,
        dest_lat=39.9590,
        dest_lng=116.4518,
    )
    ride_task.publish()

    candidates = server.resource_repo.find_available(DomainTag.of("ride"))
    result = server.match_strategy_for("ride").execute(ride_task, candidates)
    assert result.matched
    assert result.selected_resource_id == driver.resource_id

    # === escort 流程（最小验证：策略存在且可调用）===
    escort_strategy = server.match_strategy_for("escort")
    assert escort_strategy is not None

    # === group_buying 流程（最小验证：策略存在且类型正确）===
    from umcp_core.layers.l3 import ReverseAuction
    gb_strategy = server.match_strategy_for("group_buying")
    assert isinstance(gb_strategy, ReverseAuction)


def _make_task(domain: str) -> CustomTask:
    from umcp_core.core.task import CustomTask
    return CustomTask(
        demander_id="u1",
        domain_tag=DomainTag.of(domain),
    )
```

- [ ] **步骤 2：运行测试验证通过**

运行：`python -m pytest tests/test_end_to_end_multi_plugin.py -v`
预期：PASS（6 个测试全部通过）

如果某个测试失败，根据失败信息修复。常见问题：
- `match_strategy_for` 返回 None：检查插件 manifest 是否添加了 `domain` 字段
- `check_access` 行为不符：检查 `_apply_manifest` 是否把 access_rule 注册到了正确 domain
- `record_evaluation` 报错：检查 `WeightedSumTrustEngine` 的 `evaluate` 方法签名

- [ ] **步骤 3：运行全量测试确认无回归**

运行：`python -m pytest -q`
预期：224 + 6 = 230 passed

- [ ] **步骤 4：Commit**

```bash
git add tests/test_end_to_end_multi_plugin.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "test: 多插件并存端到端测试"
```

---

## 任务 5：Demo 脚本

**文件：**
- 创建：`examples/multi_plugin_demo.py`

- [ ] **步骤 1：编写 demo 脚本**

新建 `examples/multi_plugin_demo.py`：

```python
"""多插件并存 Demo：在同一 UMCPServer 上跑通三 domain 完整流程。

验证目标：
1. 三个插件可同时加载到同一 server
2. 按 domain 路由到各自的 match_strategy / payment_schema / trust_engine
3. access_rule 按 domain 隔离，互不串扰
"""
from __future__ import annotations

from umcp_core.core import DomainTag
from umcp_core.core.domain import Credential
from umcp_core.server import UMCPServer


def main() -> None:
    print("=" * 60)
    print("UMCP 多插件并存 Demo")
    print("=" * 60)

    # ===== 1. 加载三个插件 =====
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("ride_hailing")
    server.load_plugin("escort_driving")
    server.load_plugin("group_buying")
    server.start()

    print(f"\n[1] 已加载插件: {[p.name for p in server.plugins]}")

    # ===== 2. 验证策略路由 =====
    from umcp_core.layers.l3 import InstantMatch, ReverseAuction
    from umcp_core.layers.l4 import DynamicPricing, InstallmentPayment

    ride_match = server.match_strategy_for("ride")
    escort_match = server.match_strategy_for("escort")
    gb_match = server.match_strategy_for("group_buying")

    print(f"\n[2] 匹配策略路由:")
    print(f"    ride         -> {type(ride_match).__name__}")
    print(f"    escort       -> {type(escort_match).__name__}")
    print(f"    group_buying -> {type(gb_match).__name__}")
    assert isinstance(ride_match, InstantMatch)
    assert isinstance(gb_match, ReverseAuction)

    ride_pay = server.payment_schema_for("ride")
    gb_pay = server.payment_schema_for("group_buying")
    print(f"\n[3] 支付模式路由:")
    print(f"    ride         -> {type(ride_pay).__name__} (commission_rate={ride_pay.commission_rule.rate})")
    print(f"    group_buying -> {type(gb_pay).__name__} (deposit_ratio={gb_pay.deposit_ratio}, commission_rate={gb_pay.commission_rule.rate})")
    assert isinstance(ride_pay, DynamicPricing)
    assert isinstance(gb_pay, InstallmentPayment)

    # ===== 3. 验证 access_rule 隔离 =====
    from umcp_core.core.base import User
    from umcp_core.core.task import CustomTask

    # 用户只有 business_license
    gb_user = User(user_id="gb_buyer", phone="13800000001")
    gb_user.metadata["credentials"] = ["business_license"]
    gb_user.metadata["trust_score"] = 5.0

    ride_task = CustomTask(demander_id="gb_buyer", domain_tag=DomainTag.of("ride"))
    gb_task = CustomTask(demander_id="gb_buyer", domain_tag=DomainTag.of("group_buying"))

    ride_access = server.rule_engine.check_access(gb_user, ride_task)
    gb_access = server.rule_engine.check_access(gb_user, gb_task)

    print(f"\n[4] access_rule 隔离:")
    print(f"    用户 credentials=['business_license'], trust_score=5.0")
    print(f"    ride task 访问检查: {ride_access} (应 False，缺 driver_license)")
    print(f"    group_buying task 访问检查: {gb_access} (应 True)")
    assert ride_access is False
    assert gb_access is True

    # ===== 4. 简化的 ride 完整流程 =====
    from ride_hailing.resources import DriverResource
    from ride_hailing.tasks import RideTask

    passenger = server.auth_provider.authenticate(Credential.phone("13800000002"))
    driver_user = server.auth_provider.authenticate(Credential.phone("13900000003"))
    passenger.switch_role("demander")
    driver_user.switch_role("supplier")
    server.user_repo.save(passenger)
    server.user_repo.save(driver_user)

    driver = DriverResource(
        supplier_id=driver_user.user_id,
        domain_tag=DomainTag.of("ride"),
        current_lat=39.905,
        current_lng=116.408,
    )
    driver.register()
    server.resource_repo.save(driver)

    ride_task_full = RideTask(
        demander_id=passenger.user_id,
        domain_tag=DomainTag.of("ride"),
        origin_lat=39.9042,
        origin_lng=116.4074,
        dest_lat=39.9590,
        dest_lng=116.4518,
        title="多插件 Demo 乘车",
    )
    ride_task_full.bind_event_bus(server.event_bus)
    ride_task_full.publish()
    server.task_repo.save(ride_task_full)

    candidates = server.resource_repo.find_available(DomainTag.of("ride"))
    result = server.match_strategy_for("ride").execute(ride_task_full, candidates)
    print(f"\n[5] ride 完整匹配流程:")
    print(f"    任务: {ride_task_full.title}")
    print(f"    匹配结果: {result.matched}, 司机: {result.selected_resource_id}")
    assert result.matched

    print("\n" + "=" * 60)
    print("Demo 完成：三插件并存，按 domain 路由正确，access_rule 隔离正确")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

- [ ] **步骤 2：运行 demo 验证**

运行：`python examples/multi_plugin_demo.py`
预期：脚本无异常退出，输出包含：
- `[1] 已加载插件: ['ride-hailing', 'escort-driving', 'group-buying']`
- `[2] 匹配策略路由: ride -> InstantMatch, escort -> InstantMatch, group_buying -> ReverseAuction`
- `[3] 支付模式路由: ride -> DynamicPricing (commission_rate=0.2), group_buying -> InstallmentPayment (deposit_ratio=0.3, commission_rate=0.05)`
- `[4] access_rule 隔离: ride task 访问检查: False, group_buying task 访问检查: True`
- `[5] ride 完整匹配流程: 匹配结果: True`
- 末尾 `Demo 完成` 总结

- [ ] **步骤 3：运行全量测试最终确认**

运行：`python -m pytest -q`
预期：230 passed

- [ ] **步骤 4：Commit**

```bash
git add examples/multi_plugin_demo.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "demo: 多插件并存 demo 脚本"
```

---

## 验收清单

完成全部 5 个任务后，逐项确认：

- [ ] 6 个单元测试全部通过（`tests/test_multi_plugin_routing.py` 中 8 个测试，覆盖规格中 6 个验证点 + 2 个补充）
- [ ] 6 个端到端测试全部通过（`tests/test_end_to_end_multi_plugin.py`）
- [ ] 现有 224 个测试零改动通过（X2 兼容性直接验证）
- [ ] 三个插件的 `PLUGIN_MANIFEST` 与 `plugin.json` 都包含 `domain` 字段
- [ ] `examples/multi_plugin_demo.py` 可独立运行，输出证明三 domain 路由正确
- [ ] 核心库改动文件数 = 2（`server.py`、`governance.py`）
- [ ] 抽象基类（`MatchStrategy` / `PaymentSchema` / `TrustEngine` / `AccessRule`）零修改
- [ ] 总测试数：224 + 8 + 6 = 238 passed

## 自检

**规格覆盖度：**
- §3.1 server.py 多策略注册表 → 任务 2
- §3.2 governance.py RuleEngine 改造 → 任务 1
- §3.3 domain.py 无需改动 → 无任务（已确认）
- §4.1 三个插件 manifest 加 domain → 任务 3
- §4.2 register_plugin 钩子改用 register_* → 任务 3
- §4.3 现有插件测试零改动 → 任务 3 步骤 4/5 验证
- §4.4 不新增插件包 → 无任务（约束）
- §5.1 单元测试 → 任务 1+2
- §5.2 端到端测试 → 任务 4
- §5.3 Demo → 任务 5
- §5.4 不破坏现有测试 → 每个任务步骤 5 验证
- §6.1 向后兼容保证 → 任务 2 步骤 3c 中 `_apply_manifest` 容错 + `register_*` 同时更新单值
- §6.2 迁移路径 → 任务 3 演示
- §6.3 已知限制 → 不在 A 阶段范围
- §7 验收标准 → 验收清单

无遗漏。

**占位符扫描：** 无 TODO / 待定 / "类似任务 N"。所有步骤含完整代码块。✅

**类型一致性：**
- `register_match_strategy(domain: str, strategy: MatchStrategy)` 在任务 2 定义，任务 3 调用，签名一致
- `match_strategy_for(domain: DomainTag | str) -> MatchStrategy | None` 在任务 2 定义，任务 4/5 调用，签名一致
- `add_access_rule(rule, domain=None)` 在任务 1 定义，任务 2 调用，签名一致
- `_apply_manifest` 中 `domains: list[str]` 处理一致

✅ 类型一致。
