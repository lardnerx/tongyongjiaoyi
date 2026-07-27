# 阶段四 B：跨域身份与信用 设计规格

**日期**：2026-07-27
**状态**：已确认，待编写实现计划
**前置**：阶段四 A（多插件并存，已实现，commit `20d05d1`）
**后续**：阶段四 C（复合任务编排）

## 1. 目标与范围

### 1.1 目标

让同一用户的 `trust_score` 按 domain 隔离（打车评价不影响集采信任分），
同时提供跨 domain 聚合视图。

**核心矛盾**：
- 阶段四 A 已让 `TrustEngine` 按 domain 路由（每个 domain 一个 engine 实例，
  评价数据天然隔离在 `_profiles` 里）
- 但 `user.metadata["trust_score"]` 仍是单值共享，被 `ExpressionAccessRule`
  用于准入判断，导致 ride 域的低分会卡住 group_buying 域的访问

B 阶段解决这个矛盾：让 access_rule 读取的 `trustScore` 按 `task.domain_tag`
路由到对应 domain 的 TrustEngine，而非读共享的 `user.metadata`。

### 1.2 端到端验证锚点

同一 UMCPServer 实例同时加载三个插件，同一用户：
- 在 ride 域打分 5.0，在 group_buying 域仍为 0.0（隔离）
- ride task 用 ride 域 score 判断准入，gb task 用 gb 域 score 判断（不串扰）
- `server.aggregate_trust_score(user_id)` 返回跨 domain 聚合分

### 1.3 不在本阶段范围

- credentials 跨 domain 隔离（用户决策：仅隔离 trust_score）
- 复合任务编排（C 阶段）
- 跨域资源（C 阶段）
- 交易量加权聚合（默认实现是算术平均；交易量加权可作为自定义聚合器
  由插件注入，但不在 B 阶段实现）

## 2. 核心决策

| 决策点 | 选择 | 说明 |
|--------|------|------|
| 隔离范围 | 仅 `trust_score` | `credentials` 仍跨 domain 共享（一个人可同时持 driver_license 和 business_license） |
| 聚合视图 | 提供 `TrustAggregator` 抽象 + 默认实现 | 跨 domain 聚合 trust_score |
| 聚合策略 | 抽象接口 + `MeanTrustAggregator` 默认实现 | 算术平均；行业插件可注入自定义实现 |
| access_rule 读取 | `RuleContext` 隐藏 domain 路由 | 按 `task.domain_tag` 取值，表达式语法不变 |
| 存储方案 | 方案 A：复用 `WeightedSumTrustEngine._profiles` | 天然 per-domain 隔离，不引入新存储组件 |

## 3. 核心库改动

### 3.1 `src/umcp_core/layers/l5/trust.py` — 新增 TrustAggregator

```python
class TrustAggregator(ABC):
    """跨 domain 信任聚合策略接口。"""

    @abstractmethod
    def aggregate(
        self,
        user_id: str,
        engines: dict[str, TrustEngine],
    ) -> float:
        """跨 domain 聚合 trust_score。

        Args:
            user_id: 用户 ID
            engines: domain → TrustEngine 映射（只含已注册的 domain）

        Returns:
            聚合后的 trust_score（0.0-5.0）
        """


class MeanTrustAggregator(TrustAggregator):
    """算术平均聚合策略（默认实现）。

    对每个 domain 的 TrustEngine.evaluate(user_id).overall_score
    取算术平均。未注册任何 engine 时返回 0.0。
    """

    def aggregate(
        self,
        user_id: str,
        engines: dict[str, TrustEngine],
    ) -> float:
        if not engines:
            return 0.0
        scores = [
            engines[domain].evaluate(user_id).overall_score
            for domain in engines
        ]
        return sum(scores) / len(scores) if scores else 0.0
```

**职责边界**：
- `TrustAggregator` 只负责"如何聚合"，不持有数据
- 输入是 `engines` 字典（由 server 传入），输出是聚合分
- 默认实现 `MeanTrustAggregator` 简单算术平均，行业插件可注入自定义实现
  （如交易量加权）

### 3.2 `src/umcp_core/layers/l7/governance.py` — RuleEngine 与 RuleContext 改造

**RuleEngine 新增字段与方法**：

```python
class RuleEngine:
    def __init__(self) -> None:
        self._access_rules: list[AccessRule] = []
        self._domain_access_rules: dict[str, list[AccessRule]] = {}
        # 新增：domain → TrustEngine 映射（用于 RuleContext.trust_score 路由）
        self._domain_trust_engines: dict[str, TrustEngine] = {}
        self._arbitration_policy: ArbitrationPolicy = SimpleArbitrationPolicy()
        self._compliance: ComplianceModule = NoopComplianceModule()

    def add_access_rule(self, rule: AccessRule, domain: str | None = None) -> None:
        # 不变
        ...

    # 新增方法
    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None:
        """注册 domain 对应的 TrustEngine，供 RuleContext.trust_score 路由。"""
        self._domain_trust_engines[domain.lower()] = engine

    def check_access(self, user: User, task: Task) -> bool:
        domain = task.domain_tag.value
        rules = self._domain_access_rules.get(domain, []) + self._access_rules
        # 注入 domain→engine 路由能力到 ExpressionAccessRule（仅一次，幂等）
        for rule in rules:
            if isinstance(rule, ExpressionAccessRule) and rule._trust_engine_lookup is None:
                rule.bind_trust_engine_lookup(
                    lambda d: self._domain_trust_engines.get(d)
                )
        return all(rule.check(user, task) for rule in rules)
```

**RuleContext 改造**：

```python
@dataclass
class RuleContext:
    user: User
    task: Task
    # 新增：可选的 domain→engine 路由回调
    trust_engine_for_domain: Callable[[str], TrustEngine | None] | None = None

    def has_credential(self, name: str) -> bool:
        creds = self.user.metadata.get("credentials", [])
        return name in creds

    @property
    def trust_score(self) -> float:
        """按 task.domain_tag 路由到对应 TrustEngine 读取 trust_score。

        - 若 trust_engine_for_domain 已注入且能查到 domain 对应的 engine：
          返回 engine.evaluate(user_id).overall_score
        - 否则回退到 user.metadata['trust_score']（向后兼容）
        """
        if self.trust_engine_for_domain is not None:
            engine = self.trust_engine_for_domain(self.task.domain_tag.value)
            if engine is not None:
                return engine.evaluate(self.user.user_id).overall_score
        return float(self.user.metadata.get("trust_score", 0.0))
```

**ExpressionAccessRule 改造**（保持 `AccessRule` 抽象不变）：

```python
class ExpressionAccessRule(AccessRule):
    def __init__(self, expression: str) -> None:
        self.expression: str = expression
        self._trust_engine_lookup: Callable[[str], TrustEngine | None] | None = None

    def bind_trust_engine_lookup(
        self, lookup: Callable[[str], TrustEngine | None]
    ) -> None:
        """由 RuleEngine 在 check_access 前注入 domain→engine 路由能力。"""
        self._trust_engine_lookup = lookup

    def check(self, user: User, task: Task) -> bool:
        ctx = RuleContext(
            user=user,
            task=task,
            trust_engine_for_domain=self._trust_engine_lookup,
        )
        return _evaluate_expression(self.expression, ctx)
```

**向后兼容**：`ExpressionAccessRule` 不绑定 lookup 时，`RuleContext.trust_score`
回退到 `user.metadata["trust_score"]`，现有单插件测试零改动通过。

### 3.3 `src/umcp_core/server.py` — UMCPServer 持有 TrustAggregator

```python
class UMCPServer:
    def __init__(self) -> None:
        # ... 既有字段 ...
        # 新增：跨 domain 信任聚合器
        self._trust_aggregator: TrustAggregator = MeanTrustAggregator()

    def set_trust_aggregator(self, aggregator: TrustAggregator) -> None:
        """注入自定义信任聚合策略（默认 MeanTrustAggregator）。"""
        self._trust_aggregator = aggregator

    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None:
        """按 domain 注册信任引擎。

        同时：
        - 更新单值属性 self.trust_engine（兜底）
        - 注册到 self._trust_engines[domain]
        - 同步到 self.rule_engine（供 RuleContext.trust_score 路由）  ← 新增
        """
        key = domain.lower()
        self._trust_engines[key] = engine
        self.trust_engine = engine
        # 新增：同步到 RuleEngine
        self.rule_engine.register_trust_engine(key, engine)

    def aggregate_trust_score(self, user_id: str) -> float:
        """跨 domain 聚合 trust_score。

        返回所有已注册 domain 的 TrustEngine.evaluate(user_id).overall_score
        的聚合结果（默认算术平均）。
        """
        return self._trust_aggregator.aggregate(user_id, self._trust_engines)
```

**关键点**：`register_trust_engine` 在原有逻辑上新增"同步到 RuleEngine"，
确保 RuleContext 能路由到正确的 engine。

### 3.4 抽象基类零修改

- `TrustEngine` 抽象类不改（`evaluate` / `record_evaluation` 签名不变）
- `AccessRule` 抽象类不改（`check(user, task)` 签名不变）
- `MatchStrategy` / `PaymentSchema` 不涉及

## 4. 插件包改动

### 4.1 零改动

**三个插件包零改动**：
- `ride_hailing` / `escort_driving` / `group_buying` 的 `plugin.json`、
  `__init__.py`、`register_plugin` 钩子均不需要修改
- 原因：阶段四 A 已让 `register_plugin` 调用
  `server.register_trust_engine(domain, engine)`，本次改造只是让
  `register_trust_engine` 内部多了一步"同步到 RuleEngine"，对插件透明

**`PLUGIN_MANIFEST` 的 `access_rule_expression` 也不需要改**：
- 现有表达式如 `"hasCredential('driver_license') && trustScore >= 4.0"` 语法不变
- 语义变化：`trustScore` 从"读 user.metadata"变为"按 task.domain_tag 路由到
  对应 TrustEngine"，但对插件配置透明

### 4.2 不新增插件包

B 阶段只改造核心库，不创建新插件。

## 5. 测试与 demo

### 5.1 单元测试（核心库）

**新增 `tests/test_cross_domain_trust.py`**：

| 测试 | 验证点 |
|------|--------|
| `test_rule_context_trust_score_routes_by_domain` | RuleContext.trust_score 按 task.domain_tag 路由到对应 engine 的 overall_score |
| `test_rule_context_falls_back_to_metadata` | 未绑定 lookup 时回退到 user.metadata['trust_score']（向后兼容） |
| `test_rule_engine_registers_trust_engine` | RuleEngine.register_trust_engine 把 engine 加入 _domain_trust_engines |
| `test_expression_access_rule_uses_domain_score` | ExpressionAccessRule 的 trustScore 按 task.domain 取值 |
| `test_mean_trust_aggregator_empty_engines` | 无 engine 时返回 0.0 |
| `test_mean_trust_aggregator_arithmetic_mean` | 3 个 engine 的 overall_score 算术平均 |
| `test_server_aggregate_trust_score` | server.aggregate_trust_score 跨 domain 聚合 |
| `test_server_register_trust_engine_syncs_to_rule_engine` | register_trust_engine 同步到 RuleEngine |
| `test_custom_trust_aggregator_injectable` | set_trust_aggregator 可注入自定义实现 |

### 5.2 端到端测试

**新增 `tests/test_end_to_end_cross_domain_trust.py`**：

| 测试 | 验证点 |
|------|--------|
| `test_trust_score_isolated_across_domains` | 同一用户在 ride 域打分 5.0，在 group_buying 域仍为 0.0（隔离） |
| `test_access_rule_uses_domain_trust_score` | ride task 用 ride 域 score 判断准入；group_buying task 用 gb 域 score 判断（不串扰） |
| `test_aggregate_trust_score_across_domains` | ride 域 4.8 + gb 域 3.5 → 聚合 ≈ 4.15 |
| `test_low_trust_in_one_domain_blocks_only_that_domain` | ride 域低分（2.0）只卡 ride task，不卡 gb task |
| `test_custom_aggregator_via_server` | 注入自定义聚合策略（如取最低分），验证 server.aggregate_trust_score 使用它 |

### 5.3 Demo

**新增 `examples/cross_domain_trust_demo.py`**：
1. 加载三插件
2. 同一用户在 ride 域打分 5.0、gb 域打分 3.0
3. 打印各域独立 trust_score（证明隔离）
4. 打印聚合 trust_score（证明聚合）
5. 演示 ride task 因 ride 域低分被拒、gb task 因 gb 域高分通过（同一用户两种结果）

### 5.4 不破坏现有测试

所有现有测试（243 个，含阶段四 A 的 13+6 个）应零改动通过——这是
向后兼容性的直接验证。

## 6. 兼容性与迁移

### 6.1 向后兼容保证

| 现有 API | B 阶段后行为 |
|---------|-------------|
| `user.metadata["trust_score"]` | 保留，但仅在 ExpressionAccessRule 未绑定 lookup 时被读取（回退路径） |
| `ExpressionAccessRule(expression)` | 构造签名不变；首次 check_access 时由 RuleEngine 注入 lookup |
| `server.register_trust_engine(domain, engine)` | 签名不变；内部新增"同步到 RuleEngine"副作用 |
| `RuleEngine.check_access(user, task)` | 签名不变；内部新增"注入 lookup 到 ExpressionAccessRule" |
| `TrustEngine` / `AccessRule` 抽象基类 | 零修改 |
| 现有单插件测试 | 零改动通过（lookup 未绑定时回退到 metadata） |

### 6.2 迁移路径

B 阶段对插件完全透明，无需迁移：
- 插件 manifest 不变
- 插件 `register_plugin` 钩子不变
- 插件 `access_rule_expression` 不变

### 6.3 已知限制（留给 C）

- 跨域资源（一个资源同时属于多个 domain）
- 复合任务编排（一次交易串联多个插件）
- 跨域身份聚合（如统一登录态）

## 7. 验收标准

- [ ] 9 个单元测试全部通过
- [ ] 5 个端到端测试全部通过
- [ ] 现有 243 个测试零改动通过
- [ ] `examples/cross_domain_trust_demo.py` 可独立运行，输出证明隔离与聚合
- [ ] 核心库改动文件数 = 3（trust.py、governance.py、server.py）
- [ ] 抽象基类（`TrustEngine` / `AccessRule` / `MatchStrategy` / `PaymentSchema`）零修改
- [ ] 插件包零改动
- [ ] 总测试数：243 + 9 + 5 = 257 passed

## 8. 数据流

```
评价写入：
  Evaluation
    → server.trust_engine_for(domain).record_evaluation
    → _profiles[user_id]（per-domain 隔离，已由阶段四 A 实现）

access_rule 读取：
  rule.check(user, task)
    → RuleContext.trust_score
    → RuleEngine 查 _domain_trust_engines[task.domain_tag.value]
    → engine.evaluate(user_id).overall_score

聚合视图：
  server.aggregate_trust_score(user_id)
    → TrustAggregator.aggregate(user_id, _trust_engines)
    → MeanTrustAggregator: 算术平均各 engine 的 overall_score
```
