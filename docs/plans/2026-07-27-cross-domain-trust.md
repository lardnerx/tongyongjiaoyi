# 阶段四 B：跨域身份与信用 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让同一用户的 `trust_score` 按 domain 隔离（打车评价不影响集采信任分），同时提供跨 domain 聚合视图。

**架构：** 复用阶段四 A 已 per-domain 实例化的 `WeightedSumTrustEngine._profiles`（天然隔离）。新增 `TrustAggregator` 抽象 + `MeanTrustAggregator` 默认实现负责跨 domain 聚合。`RuleEngine` 持有 domain→TrustEngine 映射，`RuleContext.trust_score` 通过此映射按 `task.domain_tag` 路由取值，未绑定时回退到 `user.metadata['trust_score']`（向后兼容）。

**技术栈：** Python 3.10+ / pytest / 无第三方依赖

**规格文档：** `docs/specs/2026-07-27-cross-domain-trust-design.md`

---

## 文件结构

### 修改的文件（3 个核心库文件 + 2 个 `__init__.py` 导出）

| 文件 | 职责 | 改动类型 |
|------|------|---------|
| `src/umcp_core/layers/l5/trust.py` | 新增 `TrustAggregator` 抽象 + `MeanTrustAggregator` 默认实现 | 追加 |
| `src/umcp_core/layers/l5/__init__.py` | 导出新增的 `TrustAggregator` / `MeanTrustAggregator` | 追加导出 |
| `src/umcp_core/layers/l7/governance.py` | `RuleEngine` 持有 domain→engine 映射；`RuleContext.trust_score` 按路由取值；`ExpressionAccessRule` 新增 `bind_trust_engine_lookup` | 修改 |
| `src/umcp_core/layers/l7/__init__.py` | 无需改动（`RuleContext`/`ExpressionAccessRule`/`RuleEngine` 已导出） | 不变 |
| `src/umcp_core/server.py` | `UMCPServer` 持有 `TrustAggregator`；`register_trust_engine` 同步到 RuleEngine；新增 `aggregate_trust_score` | 修改 |

### 创建的文件（2 个测试 + 1 个 demo）

| 文件 | 职责 |
|------|------|
| `tests/test_cross_domain_trust.py` | 核心库单元测试（9 个） |
| `tests/test_end_to_end_cross_domain_trust.py` | 端到端测试（5 个） |
| `examples/cross_domain_trust_demo.py` | Demo 脚本 |

### 零改动的文件

- `src/umcp_core/core/base.py`（User 抽象）
- `src/umcp_core/core/domain.py`（DomainTag）
- `src/umcp_core/core/task.py`（Task 抽象）
- 所有插件包（`plugins/ride_hailing/*`、`plugins/escort_driving/*`、`plugins/group_buying/*`）
- 所有现有测试

---

## 任务分解

### 任务 1：新增 TrustAggregator 抽象 + MeanTrustAggregator 默认实现

**文件：**
- 修改：`src/umcp_core/layers/l5/trust.py`（在文件末尾追加）
- 修改：`src/umcp_core/layers/l5/__init__.py`（追加导出）
- 测试：`tests/test_cross_domain_trust.py`（新建）

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_cross_domain_trust.py`：

```python
"""跨域身份与信用单元测试。"""
from __future__ import annotations

from umcp_core.layers.l5 import (
    MeanTrustAggregator,
    TrustAggregator,
    TrustEngine,
    WeightedSumTrustEngine,
)
from umcp_core.layers.l5.trust import Evaluation


def test_mean_trust_aggregator_empty_engines():
    """无 engine 时返回 0.0。"""
    aggregator = MeanTrustAggregator()
    assert aggregator.aggregate("u1", {}) == 0.0


def test_mean_trust_aggregator_arithmetic_mean():
    """3 个 engine 的 overall_score 算术平均。"""
    # 准备 3 个 engine，分别给 u1 打分到不同 overall_score
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_escort = WeightedSumTrustEngine(dimensions=["overall"])
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])

    # ride 域打 5.0
    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    # escort 域打 4.0
    engine_escort.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 4.0})
    )
    # gb 域打 3.0
    engine_gb.record_evaluation(
        Evaluation(evaluator_id="e3", evaluatee_id="u1", task_id="t3", ratings={"overall": 3.0})
    )

    engines = {"ride": engine_ride, "escort": engine_escort, "group_buying": engine_gb}
    aggregator = MeanTrustAggregator()
    # 算术平均 (5.0 + 4.0 + 3.0) / 3 = 4.0
    assert aggregator.aggregate("u1", engines) == 4.0


def test_mean_trust_aggregator_user_not_in_engine():
    """用户在某 engine 没有评价记录时，overall_score 为 0.0，纳入平均。"""
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    # engine_gb 中 u1 没有记录，evaluate 会创建空 profile（overall=0.0）
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])

    engines = {"ride": engine_ride, "group_buying": engine_gb}
    aggregator = MeanTrustAggregator()
    # (5.0 + 0.0) / 2 = 2.5
    assert aggregator.aggregate("u1", engines) == 2.5


def test_trust_aggregator_is_abstract():
    """TrustAggregator 是抽象基类，不能直接实例化。"""
    import pytest
    with pytest.raises(TypeError):
        TrustAggregator()  # type: ignore[abstract]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_cross_domain_trust.py -v`
预期：FAIL，报错 `ImportError: cannot import name 'MeanTrustAggregator' from 'umcp_core.layers.l5'`

- [ ] **步骤 3：实现 TrustAggregator 与 MeanTrustAggregator**

在 `src/umcp_core/layers/l5/trust.py` 文件**末尾**追加（注意：`RatingAggregator`/`CredibilityModel`/`BadgeSystem` 这些别名保留不变，新内容追加到文件最后）：

```python
class TrustAggregator(ABC):
    """跨 domain 信任聚合策略接口。

    用于跨 domain 聚合同一用户的 trust_score。
    默认实现为 MeanTrustAggregator（算术平均），行业应用可注入
    自定义实现（如交易量加权平均、取最低分等）。
    """

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

    注意：未在某 engine 中留过评价记录的用户，evaluate() 会返回
    overall_score=0.0 的空 profile，仍纳入平均（这通常是期望行为：
    新用户从 0 分起步）。
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

- [ ] **步骤 4：在 `__init__.py` 中导出**

修改 `src/umcp_core/layers/l5/__init__.py`，在 import 列表中追加：

```python
from umcp_core.layers.l5.trust import (
    BadgeSystem,  # 9.2 命名兼容
    CredibilityModel,  # 9.2 命名兼容
    CredibilityScore,
    CredentialValidator,
    Evaluation,
    MeanTrustAggregator,  # 新增
    RatingAggregator,  # 9.2 命名兼容
    RiskWeight,
    SimpleCredentialValidator,
    SimpleRating,
    SkillBadge,
    TrustAggregator,  # 新增
    TrustEngine,
    TrustProfile,
    WeightedSumTrustEngine,
)

__all__ = [
    "TrustEngine",
    "TrustProfile",
    "Evaluation",
    "RiskWeight",
    "CredentialValidator",
    "SimpleCredentialValidator",
    "WeightedSumTrustEngine",
    "SimpleRating",
    "CredibilityScore",
    "SkillBadge",
    "RatingAggregator",
    "CredibilityModel",
    "BadgeSystem",
    "TrustAggregator",  # 新增
    "MeanTrustAggregator",  # 新增
]
```

- [ ] **步骤 5：运行测试验证通过**

运行：`pytest tests/test_cross_domain_trust.py -v`
预期：4 个测试全部 PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/layers/l5/trust.py src/umcp_core/layers/l5/__init__.py tests/test_cross_domain_trust.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(l5): 新增 TrustAggregator 抽象与 MeanTrustAggregator 默认实现"
```

---

### 任务 2：RuleContext 按 domain 路由 trust_score

**文件：**
- 修改：`src/umcp_core/layers/l7/governance.py`（`RuleContext` 数据类 + `ExpressionAccessRule` 类）
- 测试：`tests/test_cross_domain_trust.py`（追加测试）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_cross_domain_trust.py` 末尾追加：

```python
import pytest

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.layers.l7 import ExpressionAccessRule, RuleContext, RuleEngine


class _ConcreteUser(User):
    """User 是 ABC，测试中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def _make_user(credentials=None, trust_score=5.0):
    user = _ConcreteUser(user_id="u1", name="alice")
    user.metadata["credentials"] = credentials or []
    user.metadata["trust_score"] = trust_score
    return user


def _make_task(domain):
    return CustomTask(demander_id="u1", domain_tag=DomainTag.of(domain))


def test_rule_context_trust_score_routes_by_domain():
    """RuleContext.trust_score 按 task.domain_tag 路由到对应 engine 的 overall_score。"""
    engine_ride = WeightedSumTrustEngine(dimensions=["overall"])
    engine_ride.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    engine_gb = WeightedSumTrustEngine(dimensions=["overall"])
    engine_gb.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.0})
    )

    # user.metadata['trust_score'] 设为 1.0（不应该被读到）
    user = _make_user(trust_score=1.0)
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # 注入 domain→engine 路由
    ctx_ride = RuleContext(
        user=user,
        task=ride_task,
        trust_engine_for_domain=lambda d: {"ride": engine_ride, "group_buying": engine_gb}.get(d),
    )
    ctx_gb = RuleContext(
        user=user,
        task=gb_task,
        trust_engine_for_domain=lambda d: {"ride": engine_ride, "group_buying": engine_gb}.get(d),
    )

    # 应该读到对应 domain 的 engine 分数，而非 metadata
    assert ctx_ride.trust_score == 5.0
    assert ctx_gb.trust_score == 3.0


def test_rule_context_falls_back_to_metadata():
    """未绑定 lookup 时回退到 user.metadata['trust_score']（向后兼容）。"""
    user = _make_user(trust_score=4.2)
    task = _make_task("ride")
    ctx = RuleContext(user=user, task=task)  # 不传 trust_engine_for_domain
    assert ctx.trust_score == 4.2


def test_rule_context_falls_back_when_domain_not_registered():
    """lookup 已注入但 task.domain 没有对应 engine 时，回退到 metadata。"""
    user = _make_user(trust_score=4.5)
    task = _make_task("unknown_domain")
    # 只注册了 ride，task 是 unknown_domain
    ctx = RuleContext(
        user=user,
        task=task,
        trust_engine_for_domain=lambda d: {"ride": WeightedSumTrustEngine()}.get(d),
    )
    assert ctx.trust_score == 4.5
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_cross_domain_trust.py::test_rule_context_trust_score_routes_by_domain tests/test_cross_domain_trust.py::test_rule_context_falls_back_to_metadata tests/test_cross_domain_trust.py::test_rule_context_falls_back_when_domain_not_registered -v`
预期：FAIL，报错 `TypeError: RuleContext.__init__() got an unexpected keyword argument 'trust_engine_for_domain'`

- [ ] **步骤 3：改造 RuleContext 与 ExpressionAccessRule**

修改 `src/umcp_core/layers/l7/governance.py`：

**3a. 在文件顶部追加 import**（已有的 `from typing import Any` 改为追加 `Callable`）：

将原文件第 8 行：
```python
from typing import Any
```
改为：
```python
from typing import Any, Callable
```

并在 import 区块中追加（紧跟 `from umcp_core.core.task import Task` 之后）：
```python
from umcp_core.layers.l5 import TrustEngine
```

**3b. 改造 `RuleContext`**（原文件 106-120 行附近）：

将原 `RuleContext` 类替换为：

```python
@dataclass
class RuleContext:
    """规则求值上下文。"""

    user: User
    task: Task
    # 可选：domain → TrustEngine 路由回调
    # 注入后，trust_score 会按 task.domain_tag 路由到对应 engine 取值；
    # 未注入（None）时回退到 user.metadata['trust_score']（向后兼容）。
    trust_engine_for_domain: Callable[[str], TrustEngine | None] | None = None

    def has_credential(self, name: str) -> bool:
        # 简化：检查用户 metadata 中的 credentials 列表
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

**3c. 改造 `ExpressionAccessRule`**（原文件 23-37 行附近）：

将原 `ExpressionAccessRule` 类替换为：

```python
class ExpressionAccessRule(AccessRule):
    """基于表达式的准入规则。

    支持简化的表达式语法，例：
      hasCredential('driver_license') && trustScore >= 4.0

    当由 RuleEngine.check_access 调用时，会通过 bind_trust_engine_lookup
    注入 domain→TrustEngine 路由能力，使 trustScore 按 task.domain_tag
    路由到对应 engine 取值。未绑定时 trustScore 读 user.metadata。
    """

    def __init__(self, expression: str) -> None:
        self.expression: str = expression
        self._trust_engine_lookup: Callable[[str], TrustEngine | None] | None = None

    def bind_trust_engine_lookup(
        self, lookup: Callable[[str], TrustEngine | None]
    ) -> None:
        """由 RuleEngine 在 check_access 前注入 domain→engine 路由能力。

        幂等：重复调用不会覆盖已绑定的 lookup。
        """
        if self._trust_engine_lookup is None:
            self._trust_engine_lookup = lookup

    def check(self, user: User, task: Task) -> bool:
        ctx = RuleContext(
            user=user,
            task=task,
            trust_engine_for_domain=self._trust_engine_lookup,
        )
        return _evaluate_expression(self.expression, ctx)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_cross_domain_trust.py -v`
预期：所有 7 个测试 PASS（4 个原 MeanTrustAggregator 测试 + 3 个新增 RuleContext 测试）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/layers/l7/governance.py tests/test_cross_domain_trust.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(l7): RuleContext 按 task.domain 路由 trust_score，回退到 metadata 保持兼容"
```

---

### 任务 3：RuleEngine 持有 domain→TrustEngine 映射并在 check_access 注入路由能力

**文件：**
- 修改：`src/umcp_core/layers/l7/governance.py`（`RuleEngine` 类）
- 测试：`tests/test_cross_domain_trust.py`（追加测试）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_cross_domain_trust.py` 末尾追加：

```python
def test_rule_engine_registers_trust_engine():
    """RuleEngine.register_trust_engine 把 engine 加入 _domain_trust_engines。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])

    engine.register_trust_engine("ride", ride_te)

    assert engine._domain_trust_engines["ride"] is ride_te


def test_rule_engine_register_trust_engine_lowercases_domain():
    """register_trust_engine 将 domain 统一小写化存储。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])

    engine.register_trust_engine("RIDE", ride_te)

    # DomainTag.of('ride').value == 'ride'，查询时用小写
    assert "ride" in engine._domain_trust_engines
    assert "RIDE" not in engine._domain_trust_engines


def test_expression_access_rule_uses_domain_score():
    """ExpressionAccessRule 的 trustScore 按 task.domain 取值（通过 RuleEngine 注入）。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 2.0})
    )

    engine.register_trust_engine("ride", ride_te)
    engine.register_trust_engine("group_buying", gb_te)

    # 注册按 domain 隔离的 access_rule：trustScore >= 3.0
    engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="ride",
    )
    engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="group_buying",
    )

    user = _make_user(trust_score=1.0)  # metadata 设为 1.0，验证不被读到
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # ride 域 5.0 >= 3.0 通过
    assert engine.check_access(user, ride_task) is True
    # gb 域 2.0 < 3.0 拒绝
    assert engine.check_access(user, gb_task) is False


def test_check_access_injects_lookup_only_once():
    """check_access 注入 lookup 是幂等的（多次调用不覆盖）。"""
    engine = RuleEngine()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    engine.register_trust_engine("ride", ride_te)

    rule = ExpressionAccessRule("trustScore >= 0.0")
    engine.add_access_rule(rule, domain="ride")

    user = _make_user(trust_score=1.0)
    task = _make_task("ride")

    engine.check_access(user, task)
    first_lookup = rule._trust_engine_lookup
    assert first_lookup is not None

    # 再次调用不应覆盖
    engine.check_access(user, task)
    assert rule._trust_engine_lookup is first_lookup
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_cross_domain_trust.py::test_rule_engine_registers_trust_engine -v`
预期：FAIL，报错 `AttributeError: 'RuleEngine' object has no attribute 'register_trust_engine'`

- [ ] **步骤 3：改造 RuleEngine**

修改 `src/umcp_core/layers/l7/governance.py` 的 `RuleEngine` 类。

**3a. 在 `__init__` 中新增字段**（在 `self._domain_access_rules` 之后追加）：

将原 `__init__`：
```python
    def __init__(self) -> None:
        self._access_rules: list[AccessRule] = []
        self._domain_access_rules: dict[str, list[AccessRule]] = {}
        self._arbitration_policy: ArbitrationPolicy = SimpleArbitrationPolicy()
        self._compliance: ComplianceModule = NoopComplianceModule()
```

改为：
```python
    def __init__(self) -> None:
        self._access_rules: list[AccessRule] = []  # 全局兜底
        self._domain_access_rules: dict[str, list[AccessRule]] = {}  # 按 domain
        # domain → TrustEngine 映射，供 RuleContext.trust_score 路由
        self._domain_trust_engines: dict[str, TrustEngine] = {}
        self._arbitration_policy: ArbitrationPolicy = SimpleArbitrationPolicy()
        self._compliance: ComplianceModule = NoopComplianceModule()
```

**3b. 新增 `register_trust_engine` 方法**（在 `add_access_rule` 方法之后、`set_arbitration_policy` 之前插入）：

```python
    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None:
        """注册 domain 对应的 TrustEngine，供 RuleContext.trust_score 路由。

        domain 统一小写化存储，与 DomainTag.of(...).value 保持一致。
        """
        self._domain_trust_engines[domain.lower()] = engine
```

**3c. 改造 `check_access` 方法**：

将原 `check_access`：
```python
    def check_access(self, user: User, task: Task) -> bool:
        """检查所有准入规则。任一不通过则拒绝。

        优先校验 task.domain_tag 对应的 domain 规则，再校验全局规则。
        """
        domain = task.domain_tag.value
        rules = self._domain_access_rules.get(domain, []) + self._access_rules
        return all(rule.check(user, task) for rule in rules)
```

改为：
```python
    def check_access(self, user: User, task: Task) -> bool:
        """检查所有准入规则。任一不通过则拒绝。

        优先校验 task.domain_tag 对应的 domain 规则，再校验全局规则。
        同时向 ExpressionAccessRule 注入 domain→TrustEngine 路由能力
        （幂等：仅当 rule 未绑定时注入），使 trustScore 按 task.domain 取值。
        """
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

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_cross_domain_trust.py -v`
预期：所有 11 个测试 PASS（7 个原有 + 4 个新增）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/layers/l7/governance.py tests/test_cross_domain_trust.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(l7): RuleEngine 持有 domain→TrustEngine 映射，check_access 注入路由能力"
```

---

### 任务 4：UMCPServer 持有 TrustAggregator，register_trust_engine 同步到 RuleEngine

**文件：**
- 修改：`src/umcp_core/server.py`（`UMCPServer` 类）
- 测试：`tests/test_cross_domain_trust.py`（追加测试）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_cross_domain_trust.py` 末尾追加：

```python
from umcp_core.layers.l5 import MeanTrustAggregator, TrustAggregator
from umcp_core.server import UMCPServer


def test_server_holds_default_trust_aggregator():
    """UMCPServer 默认持有 MeanTrustAggregator 实例。"""
    server = UMCPServer()
    assert isinstance(server._trust_aggregator, MeanTrustAggregator)


def test_server_set_trust_aggregator_injectable():
    """set_trust_aggregator 可注入自定义实现。"""
    server = UMCPServer()

    class MinTrustAggregator(TrustAggregator):
        """取最低分聚合策略（自定义实现，用于测试）。"""
        def aggregate(self, user_id, engines):
            if not engines:
                return 0.0
            return min(e.evaluate(user_id).overall_score for e in engines.values())

    custom = MinTrustAggregator()
    server.set_trust_aggregator(custom)
    assert server._trust_aggregator is custom


def test_server_register_trust_engine_syncs_to_rule_engine():
    """register_trust_engine 同步注册到 RuleEngine._domain_trust_engines。"""
    server = UMCPServer()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])

    server.register_trust_engine("ride", ride_te)

    # 同步到 RuleEngine
    assert server.rule_engine._domain_trust_engines["ride"] is ride_te


def test_server_aggregate_trust_score():
    """server.aggregate_trust_score 跨 domain 聚合。"""
    server = UMCPServer()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.0})
    )

    server.register_trust_engine("ride", ride_te)
    server.register_trust_engine("group_buying", gb_te)

    # 算术平均 (5.0 + 3.0) / 2 = 4.0
    assert server.aggregate_trust_score("u1") == 4.0


def test_server_aggregate_with_custom_aggregator():
    """注入自定义聚合器（取最低分），server.aggregate_trust_score 使用它。"""
    server = UMCPServer()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.0})
    )
    server.register_trust_engine("ride", ride_te)
    server.register_trust_engine("group_buying", gb_te)

    class MinTrustAggregator(TrustAggregator):
        def aggregate(self, user_id, engines):
            if not engines:
                return 0.0
            return min(e.evaluate(user_id).overall_score for e in engines.values())

    server.set_trust_aggregator(MinTrustAggregator())
    # 取最低分 min(5.0, 3.0) = 3.0
    assert server.aggregate_trust_score("u1") == 3.0


def test_server_aggregate_trust_score_empty():
    """未注册任何 engine 时，aggregate_trust_score 返回 0.0。"""
    server = UMCPServer()
    assert server.aggregate_trust_score("u1") == 0.0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_cross_domain_trust.py::test_server_holds_default_trust_aggregator -v`
预期：FAIL，报错 `AttributeError: 'UMCPServer' object has no attribute '_trust_aggregator'`

- [ ] **步骤 3：改造 UMCPServer**

修改 `src/umcp_core/server.py`：

**3a. 在顶部 import 区追加**（紧跟 `from umcp_core.layers.l5 import TrustEngine` 之后，或修改该行）：

将原行：
```python
from umcp_core.layers.l5 import TrustEngine
```
改为：
```python
from umcp_core.layers.l5 import MeanTrustAggregator, TrustAggregator, TrustEngine
```

**3b. 在 `__init__` 末尾追加**（在 `self._started: bool = False` 之后、`self.event_bus.subscribe_all(self._audit_event)` 之前，或在 `# 按 domain 索引的策略注册表` 区块末尾）：

找到：
```python
        # 按 domain 索引的策略注册表（多插件并存支持）
        self._match_strategies: dict[str, MatchStrategy] = {}
        self._payment_schemas: dict[str, PaymentSchema] = {}
        self._trust_engines: dict[str, TrustEngine] = {}
```

在其后追加：
```python
        # 跨 domain 信任聚合器（默认算术平均）
        self._trust_aggregator: TrustAggregator = MeanTrustAggregator()
```

**3c. 改造 `register_trust_engine` 方法**：

将原方法：
```python
    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None:
        """按 domain 注册信任引擎，同时更新单值属性作为兜底。"""
        self._trust_engines[domain.lower()] = engine
        self.trust_engine = engine
```

改为：
```python
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
```

**3d. 新增 `set_trust_aggregator` 与 `aggregate_trust_score` 方法**：

在 `trust_engine_for` 方法之后、`# 任务工厂注册` 区块之前插入：

```python
    def set_trust_aggregator(self, aggregator: TrustAggregator) -> None:
        """注入自定义信任聚合策略（默认 MeanTrustAggregator）。"""
        self._trust_aggregator = aggregator

    def aggregate_trust_score(self, user_id: str) -> float:
        """跨 domain 聚合 trust_score。

        返回所有已注册 domain 的 TrustEngine.evaluate(user_id).overall_score
        的聚合结果（默认算术平均，可通过 set_trust_aggregator 自定义）。
        """
        return self._trust_aggregator.aggregate(user_id, self._trust_engines)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_cross_domain_trust.py -v`
预期：所有 17 个测试 PASS（11 个原有 + 6 个新增）

- [ ] **步骤 5：运行现有测试确认未破坏**

运行：`pytest -x`
预期：所有现有测试 PASS（243 + 17 = 260）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/server.py tests/test_cross_domain_trust.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(server): UMCPServer 持有 TrustAggregator，register_trust_engine 同步到 RuleEngine"
```

---

### 任务 5：端到端测试 - 跨域 trust_score 隔离与聚合

**文件：**
- 测试：`tests/test_end_to_end_cross_domain_trust.py`（新建）

- [ ] **步骤 1：编写测试**

创建 `tests/test_end_to_end_cross_domain_trust.py`：

```python
"""端到端测试：跨域 trust_score 隔离与聚合。"""
from __future__ import annotations

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l5 import TrustAggregator, WeightedSumTrustEngine
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.layers.l7 import ExpressionAccessRule
from umcp_core.server import UMCPServer


class _E2EUser(User):
    """User 是 ABC，测试中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def _make_user(user_id="u1", credentials=None, trust_score=5.0):
    user = _E2EUser(user_id=user_id, name="alice")
    user.metadata["credentials"] = credentials or []
    user.metadata["trust_score"] = trust_score
    return user


def _make_task(domain, demander_id="u1"):
    return CustomTask(demander_id=demander_id, domain_tag=DomainTag.of(domain))


def _setup_server_with_two_domains():
    """加载 ride + group_buying 两个 domain 的 TrustEngine。"""
    server = UMCPServer()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    server.register_trust_engine("ride", ride_te)
    server.register_trust_engine("group_buying", gb_te)
    # 按 domain 注册 access_rule：trustScore >= 3.0
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="ride",
    )
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 3.0"),
        domain="group_buying",
    )
    return server, ride_te, gb_te


def test_trust_score_isolated_across_domains():
    """同一用户在 ride 域打分 5.0，在 group_buying 域仍为 0.0（隔离）。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )

    # ride 域 u1 = 5.0
    assert ride_te.evaluate("u1").overall_score == 5.0
    # group_buying 域 u1 仍为 0.0（评价数据隔离）
    assert gb_te.evaluate("u1").overall_score == 0.0


def test_access_rule_uses_domain_trust_score():
    """ride task 用 ride 域 score 判断准入；gb task 用 gb 域 score 判断（不串扰）。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    # ride 域打 5.0，gb 域打 2.0
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 2.0})
    )

    # user.metadata['trust_score'] = 1.0（验证不被读到）
    user = _make_user(trust_score=1.0)
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # ride 域 5.0 >= 3.0 通过
    assert server.rule_engine.check_access(user, ride_task) is True
    # gb 域 2.0 < 3.0 拒绝
    assert server.rule_engine.check_access(user, gb_task) is False


def test_aggregate_trust_score_across_domains():
    """ride 域 4.8 + gb 域 3.5 → 聚合 ≈ 4.15。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    # ride 域打 4.8（通过 record_evaluation 的移动平均，需要从 0 起步打 4.8 → 4.8）
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 4.8})
    )
    # gb 域打 3.5
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.5})
    )

    # 算术平均 (4.8 + 3.5) / 2 = 4.15
    aggregated = server.aggregate_trust_score("u1")
    assert abs(aggregated - 4.15) < 0.001


def test_low_trust_in_one_domain_blocks_only_that_domain():
    """ride 域低分（2.0）只卡 ride task，不卡 gb task。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    # ride 域打 2.0（低分），gb 域打 5.0（高分）
    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 2.0})
    )
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 5.0})
    )

    user = _make_user(trust_score=1.0)  # metadata 不应被读到
    ride_task = _make_task("ride")
    gb_task = _make_task("group_buying")

    # ride 域 2.0 < 3.0 拒绝
    assert server.rule_engine.check_access(user, ride_task) is False
    # gb 域 5.0 >= 3.0 通过（不被 ride 域低分影响）
    assert server.rule_engine.check_access(user, gb_task) is True


def test_custom_aggregator_via_server():
    """注入自定义聚合策略（取最低分），验证 server.aggregate_trust_score 使用它。"""
    server, ride_te, gb_te = _setup_server_with_two_domains()

    ride_te.record_evaluation(
        Evaluation(evaluator_id="e1", evaluatee_id="u1", task_id="t1", ratings={"overall": 5.0})
    )
    gb_te.record_evaluation(
        Evaluation(evaluator_id="e2", evaluatee_id="u1", task_id="t2", ratings={"overall": 3.0})
    )

    class MinTrustAggregator(TrustAggregator):
        def aggregate(self, user_id, engines):
            if not engines:
                return 0.0
            return min(e.evaluate(user_id).overall_score for e in engines.values())

    server.set_trust_aggregator(MinTrustAggregator())
    # 取最低分 min(5.0, 3.0) = 3.0
    assert server.aggregate_trust_score("u1") == 3.0
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_end_to_end_cross_domain_trust.py -v`
预期：5 个测试全部 PASS

- [ ] **步骤 3：运行完整测试套件**

运行：`pytest -x`
预期：260 + 5 = 265 个测试 PASS

- [ ] **步骤 4：Commit**

```bash
git add tests/test_end_to_end_cross_domain_trust.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "test(e2e): 跨域 trust_score 隔离与聚合端到端测试"
```

---

### 任务 6：Demo 脚本

**文件：**
- 创建：`examples/cross_domain_trust_demo.py`

- [ ] **步骤 1：编写 demo 脚本**

创建 `examples/cross_domain_trust_demo.py`：

```python
"""跨域身份与信用 Demo。

演示：
1. 同一 UMCPServer 实例加载 ride + group_buying 两个 domain 的 TrustEngine
2. 同一用户在 ride 域打分 5.0、gb 域打分 3.0
3. 打印各域独立 trust_score（证明隔离）
4. 打印聚合 trust_score（证明聚合）
5. 演示 ride task 因 ride 域高分通过、gb task 因 gb 域低分被拒（同一用户两种结果）
"""
from __future__ import annotations

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l5 import WeightedSumTrustEngine
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.layers.l7 import ExpressionAccessRule
from umcp_core.server import UMCPServer


class _DemoUser(User):
    """User 是 ABC，demo 中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def main() -> None:
    # 1. 创建 server，注册两个 domain 的 TrustEngine
    server = UMCPServer()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    server.register_trust_engine("ride", ride_te)
    server.register_trust_engine("group_buying", gb_te)

    # 按 domain 注册 access_rule：trustScore >= 4.0
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 4.0"),
        domain="ride",
    )
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 4.0"),
        domain="group_buying",
    )

    # 2. 同一用户 alice 在两个 domain 分别打分
    alice = _DemoUser(user_id="alice", name="Alice")
    alice.metadata["trust_score"] = 1.0  # 故意设低，证明不被读到

    # ride 域：5.0（高分）
    ride_te.record_evaluation(
        Evaluation(
            evaluator_id="system",
            evaluatee_id="alice",
            task_id="ride-001",
            ratings={"overall": 5.0},
        )
    )
    # gb 域：3.0（低分）
    gb_te.record_evaluation(
        Evaluation(
            evaluator_id="system",
            evaluatee_id="alice",
            task_id="gb-001",
            ratings={"overall": 3.0},
        )
    )

    # 3. 打印各域独立 trust_score（证明隔离）
    ride_score = ride_te.evaluate("alice").overall_score
    gb_score = gb_te.evaluate("alice").overall_score
    print(f"[隔离] alice 在 ride 域 trust_score = {ride_score}")
    print(f"[隔离] alice 在 group_buying 域 trust_score = {gb_score}")
    print(f"[隔离] metadata['trust_score'] = {alice.metadata['trust_score']}（不被 access_rule 读取）")

    # 4. 打印聚合 trust_score（证明聚合）
    aggregated = server.aggregate_trust_score("alice")
    print(f"[聚合] alice 跨 domain 聚合 trust_score = {aggregated}（算术平均）")

    # 5. 演示同一用户在两个 domain 的 access_rule 结果不同
    ride_task = CustomTask(demander_id="alice", domain_tag=DomainTag.of("ride"))
    gb_task = CustomTask(demander_id="alice", domain_tag=DomainTag.of("group_buying"))

    ride_pass = server.rule_engine.check_access(alice, ride_task)
    gb_pass = server.rule_engine.check_access(alice, gb_task)

    print(f"[准入] alice 接 ride task: {'通过' if ride_pass else '拒绝'}（ride 域 5.0 >= 4.0）")
    print(f"[准入] alice 接 gb task: {'通过' if gb_pass else '拒绝'}（gb 域 3.0 < 4.0）")

    # 6. 演示自定义聚合策略
    from umcp_core.layers.l5 import TrustAggregator

    class MinTrustAggregator(TrustAggregator):
        """取最低分（防刷分策略）。"""
        def aggregate(self, user_id, engines):
            if not engines:
                return 0.0
            return min(e.evaluate(user_id).overall_score for e in engines.values())

    server.set_trust_aggregator(MinTrustAggregator())
    min_aggregated = server.aggregate_trust_score("alice")
    print(f"[自定义聚合] 切换为取最低分策略：alice 聚合 trust_score = {min_aggregated}（min(5.0, 3.0)）")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 2：运行 demo 验证输出**

运行：`python -m examples.cross_domain_trust_demo`
预期输出（类似）：
```
[隔离] alice 在 ride 域 trust_score = 5.0
[隔离] alice 在 group_buying 域 trust_score = 3.0
[隔离] metadata['trust_score'] = 1.0（不被 access_rule 读取）
[聚合] alice 跨 domain 聚合 trust_score = 4.0（算术平均）
[准入] alice 接 ride task: 通过（ride 域 5.0 >= 4.0）
[准入] alice 接 gb task: 拒绝（gb 域 3.0 < 4.0）
[自定义聚合] 切换为取最低分策略：alice 聚合 trust_score = 3.0（min(5.0, 3.0)）
```

- [ ] **步骤 3：Commit**

```bash
git add examples/cross_domain_trust_demo.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "demo: 跨域身份与信用 demo 脚本"
```

---

### 任务 7：最终代码审查 + 分支收尾

**文件：** 无新增，仅运行审查与全量测试

- [ ] **步骤 1：运行全量测试**

运行：`pytest -v`
预期：265 个测试全部 PASS

- [ ] **步骤 2：运行 demo 确认无回归**

运行：`python -m examples.cross_domain_trust_demo`
预期：输出与任务 6 步骤 2 一致

- [ ] **步骤 3：检查抽象基类零修改**

运行：`git diff main -- src/umcp_core/core/base.py src/umcp_core/core/task.py src/umcp_core/core/domain.py src/umcp_core/layers/l3 src/umcp_core/layers/l4 src/umcp_core/layers/l5/trust.py | head -50`
预期：除 `trust.py` 末尾追加 `TrustAggregator`/`MeanTrustAggregator` 外，其他抽象基类零修改

- [ ] **步骤 4：检查插件包零修改**

运行：`git diff main -- plugins/`
预期：无输出（插件包零修改）

- [ ] **步骤 5：使用 superpowers:finishing-a-development-branch 收尾**

调用 `superpowers:finishing-a-development-branch` 技能，准备展示选项。

---

## 自检结果

### 规格覆盖度

| 规格章节 | 实现任务 |
|---------|---------|
| §3.1 TrustAggregator + MeanTrustAggregator | 任务 1 |
| §3.2 RuleContext 按 domain 路由 | 任务 2 |
| §3.2 ExpressionAccessRule.bind_trust_engine_lookup | 任务 2 |
| §3.2 RuleEngine.register_trust_engine + check_access 注入 | 任务 3 |
| §3.3 UMCPServer._trust_aggregator | 任务 4 |
| §3.3 UMCPServer.set_trust_aggregator | 任务 4 |
| §3.3 UMCPServer.register_trust_engine 同步到 RuleEngine | 任务 4 |
| §3.3 UMCPServer.aggregate_trust_score | 任务 4 |
| §4.1 插件包零改动 | 任务 7 步骤 4 验证 |
| §5.1 单元测试（9 个） | 任务 1-4 共编写 17 个单元测试（覆盖规格 9 个 + 额外 8 个边界） |
| §5.2 端到端测试（5 个） | 任务 5 |
| §5.3 Demo | 任务 6 |
| §5.4 不破坏现有测试 | 任务 4 步骤 5、任务 7 步骤 1 验证 |

**所有规格需求均有对应任务。**

### 占位符扫描

无 TODO / 待定 / 模糊步骤。每个步骤都包含完整代码块或精确命令。

### 类型一致性

- `TrustAggregator.aggregate(user_id: str, engines: dict[str, TrustEngine]) -> float` — 任务 1 定义，任务 4 测试中使用，签名一致 ✅
- `MeanTrustAggregator` — 任务 1 定义，任务 4 由 `server._trust_aggregator` 持有 ✅
- `RuleContext(user, task, trust_engine_for_domain)` — 任务 2 定义，任务 3 由 `ExpressionAccessRule.check` 构造 ✅
- `ExpressionAccessRule.bind_trust_engine_lookup(lookup)` — 任务 2 定义，任务 3 由 `RuleEngine.check_access` 调用 ✅
- `RuleEngine.register_trust_engine(domain, engine)` — 任务 3 定义，任务 4 由 `server.register_trust_engine` 调用 ✅
- `server._trust_aggregator` — 任务 4 定义，任务 5 端到端测试中通过 `server.aggregate_trust_score` 间接使用 ✅
- `server.set_trust_aggregator(aggregator)` — 任务 4 定义，任务 5/6 使用 ✅
- `server.aggregate_trust_score(user_id)` — 任务 4 定义，任务 5/6 使用 ✅

**所有类型与方法签名跨任务一致。**
