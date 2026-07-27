# 阶段四 A：多插件并存 设计规格

**日期**：2026-07-27
**状态**：已确认，待编写实现计划
**前置**：阶段一/二/三（网约车、陪驾、集采插件已完成验证）
**后续**：阶段四 B（跨域身份与信用）、阶段四 C（复合任务编排）

## 1. 目标与范围

### 1.1 目标

让 UMCPServer 同时承载多个行业插件，按 `DomainTag` 路由到各自的
`match_strategy` / `payment_schema` / `trust_engine` / `access_rules`，
互不覆盖、互不串扰。

### 1.2 端到端验证锚点

同一 UMCPServer 实例同时加载 `ride_hailing` + `escort_driving` + `group_buying`
三个插件，按 domain 各自走通完整交易流程。

### 1.3 不在本阶段范围

- 跨域身份与信用传播（同一用户的打车评价不影响集采信任分）—— 留给 B
- 复合任务编排（一次交易串联多个插件）—— 留给 C
- 跨域资源（一个资源同时属于多个 domain）—— 留给 C

## 2. 核心决策

| 决策点 | 选择 | 说明 |
|--------|------|------|
| domain 声明方式 | A1 显式 `domain` 字段 | `PLUGIN_MANIFEST` / `plugin.json` 新增 `"domain": "xxx"` |
| API 形态 | X2 默认+注册表 | 保留单值属性作兜底，新增 `*_for(domain)` 方法优先查注册表 |
| 准入规则归属 | Y2 按 domain 路由 | `RuleEngine` 维护 domain → access_rules 映射 |

## 3. 核心库改动

### 3.1 `src/umcp_core/server.py` — 多策略注册表

`UMCPServer` 内部新增三个按 DomainTag 索引的注册表：

```python
class UMCPServer:
    def __init__(self) -> None:
        # ... 既有单值字段保留作为"默认/兜底" ...
        self.match_strategy: MatchStrategy | None = None
        self.payment_schema: PaymentSchema | None = None
        self.trust_engine: TrustEngine | None = None
        # 新增：按 domain 索引的注册表
        self._match_strategies: dict[str, MatchStrategy] = {}
        self._payment_schemas: dict[str, PaymentSchema] = {}
        self._trust_engines: dict[str, TrustEngine] = {}

    # 新增：按 domain 注册（同时更新单值属性作为兜底）
    def register_match_strategy(self, domain: str, strategy: MatchStrategy) -> None: ...
    def register_payment_schema(self, domain: str, schema: PaymentSchema) -> None: ...
    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None: ...

    # 新增：按 domain 查询，未命中回退到默认
    def match_strategy_for(self, domain: DomainTag | str) -> MatchStrategy | None: ...
    def payment_schema_for(self, domain: DomainTag | str) -> PaymentSchema | None: ...
    def trust_engine_for(self, domain: DomainTag | str) -> TrustEngine | None: ...
```

**`register_*` 方法语义**：
- 注册到 `_xxx[domain] = component`
- 同时更新单值属性 `self.xxx = component`（指向最后注册的策略，向后兼容）

**`*_for(domain)` 方法语义**：
- 接受 `DomainTag` 或 `str`，统一 `.value` 取值
- 优先查 `_xxx.get(domain_value)`
- 未命中时回退到单值属性 `self.xxx`
- 单值属性也为 None 时返回 None

**`_apply_manifest` 改造**：
- 读取 `manifest["domain"]`（字符串或字符串列表）
- 对每个 domain 调用 `register_*` 注册插件策略
- 缺 `domain` 字段时容错：只更新单值属性，不注册到 domain 表（向后兼容旧插件）

### 3.2 `src/umcp_core/layers/l7/governance.py` — RuleEngine 按 domain 路由

```python
class RuleEngine:
    def __init__(self) -> None:
        self._access_rules: list[AccessRule] = []               # 全局兜底
        self._domain_access_rules: dict[str, list[AccessRule]] = {}  # 按 domain

    def add_access_rule(self, rule: AccessRule, domain: str | None = None) -> None:
        if domain is None:
            self._access_rules.append(rule)
        else:
            self._domain_access_rules.setdefault(domain, []).append(rule)

    def check_access(self, user: User, task: Task) -> bool:
        domain = task.domain_tag.value
        rules = self._domain_access_rules.get(domain, []) + self._access_rules
        return all(rule.check(user, task) for rule in rules)
```

`server._apply_manifest` 加载插件时：
```python
domain = manifest.get("domain")
rule = ExpressionAccessRule(manifest["access_rule_expression"])
self.rule_engine.add_access_rule(rule, domain=domain)
```

`domain` 为 None 时退化为全局规则（向后兼容）。

### 3.3 `src/umcp_core/core/domain.py` — 无需改动

`DomainTag` 已是 `frozen=True` dataclass，可哈希、可作 dict 键。

## 4. 插件包改动

### 4.1 三个已有插件 manifest 新增 `domain` 字段

| 插件 | domain 值 |
|------|----------|
| `ride_hailing/plugin.json` + `__init__.py` | `"ride"` |
| `escort_driving/plugin.json` + `__init__.py` | `"escort"` |
| `group_buying/plugin.json` + `__init__.py` | `"group_buying"` |

`PLUGIN_MANIFEST` 字典与 `plugin.json` 文件各加一行 `"domain": "xxx"`，
保持两者一致。

### 4.2 `register_plugin` 钩子改为按 domain 注册

以 `group_buying/__init__.py` 为例：

```python
def register_plugin(server: "UMCPServer") -> None:
    domain = PLUGIN_MANIFEST["domain"]  # "group_buying"
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

**不重复调 `set_*`**：`register_*` 内部已同时更新单值属性作为兜底。

### 4.3 现有插件测试与 demo 零改动

由于 X2（默认+注册表）保留单值属性语义，所有
`server.match_strategy.execute(...)` 形式的代码继续工作。
仅在新场景（多插件并存）中使用 `*_for(domain)` 方法。

### 4.4 不新增插件包

A 阶段只验证"现有三个插件同时加载"，不创建新插件。

## 5. 测试与 demo

### 5.1 单元测试（核心库）

**新增 `tests/test_multi_plugin_routing.py`**：

| 测试 | 验证点 |
|------|--------|
| `test_register_match_strategy_by_domain` | `register_match_strategy("ride", s)` 后 `match_strategy_for("ride")` 返回 s |
| `test_match_strategy_for_falls_back_to_default` | 未注册 domain 时回退到 `server.match_strategy` 单值属性 |
| `test_payment_schema_routing` | 同上，针对 payment_schema |
| `test_trust_engine_routing` | 同上，针对 trust_engine |
| `test_rule_engine_domain_scoped_access` | ride 的 access_rule 不影响 group_buying task 的访问检查 |
| `test_rule_engine_global_fallback` | `add_access_rule(rule)` 无 domain 时对所有 domain 生效 |

### 5.2 端到端测试

**新增 `tests/test_end_to_end_multi_plugin.py`**：

| 测试 | 验证点 |
|------|--------|
| `test_load_three_plugins_simultaneously` | 同一 server 加载 3 个插件，`server.plugins` 长度为 3，无报错 |
| `test_each_domain_uses_own_strategy` | ride task 用 InstantMatch，group_buying task 用 ReverseAuction，分别走通匹配 |
| `test_each_domain_uses_own_payment` | ride 走担保支付（20% 抽成），group_buying 走分期（5% 抽成 + 30% 订金） |
| `test_each_domain_uses_own_trust_dimensions` | ride 评价维度与 group_buying 评价维度独立存储 |
| `test_access_rule_does_not_leak_across_domains` | ride 的 driver_license 要求不卡 group_buying 买家 |
| `test_three_full_flows_in_one_server` | 同一 server 内串行执行三个完整交易流程，互不串扰 |

### 5.3 Demo

**新增 `examples/multi_plugin_demo.py`**：在同一 UMCPServer 实例上：
1. 加载三个插件
2. 创建三个 domain 的用户、任务、资源
3. 各自走通完整交易流程
4. 打印每个 domain 使用的策略类型，证明路由正确

### 5.4 不破坏现有测试

所有现有单插件测试（`test_end_to_end_plugin.py`、`test_end_to_end_escort.py`、
`test_end_to_end_group_buying.py`）应零改动通过——这是 X2 兼容性的直接验证。

## 6. 兼容性与迁移

### 6.1 向后兼容保证

| 现有 API | A 阶段后行为 |
|---------|-------------|
| `server.match_strategy`（属性） | 保留，指向最后注册的策略（向后兼容） |
| `server.set_match_strategy(s)` | 保留，等价于设置默认策略（无 domain） |
| `server.payment_schema` / `set_payment_schema` | 同上 |
| `server.trust_engine` / `set_trust_engine` | 同上 |
| `rule_engine.add_access_rule(rule)` | 保留，无 domain 参数时注册为全局规则 |
| `rule_engine.check_access(user, task)` | 保留签名，内部按 `task.domain_tag` 路由 |
| 现有 `PLUGIN_MANIFEST`（无 `domain` 字段） | `_apply_manifest` 容错：缺 `domain` 时只更新单值属性，不注册到 domain 表 |

### 6.2 迁移路径

旧插件升级到 A 阶段只需两步：
1. `plugin.json` 与 `PLUGIN_MANIFEST` 添加 `"domain": "xxx"`
2. `register_plugin` 钩子内 `server.set_*` 改为 `server.register_*(domain, ...)`

不升级也能工作（向后兼容），但无法享受多插件并存能力。

### 6.3 已知限制（留给 B/C）

- 同一用户的身份与信用分跨 domain 隔离（B 阶段统一）
- 资源只能属于单一 domain（C 阶段如需跨域资源再扩展）
- 复合任务编排（C 阶段处理）

## 7. 验收标准

- [ ] 6 个单元测试全部通过
- [ ] 6 个端到端测试全部通过
- [ ] 现有 224 个测试零改动通过（X2 兼容性直接验证）
- [ ] 三个插件的 `PLUGIN_MANIFEST` 与 `plugin.json` 都包含 `domain` 字段
- [ ] `examples/multi_plugin_demo.py` 可独立运行，输出证明三 domain 路由正确
- [ ] 核心库改动文件数 ≤ 2（server.py、governance.py）
- [ ] 抽象基类（`MatchStrategy` / `PaymentSchema` / `TrustEngine` / `AccessRule`）零修改
