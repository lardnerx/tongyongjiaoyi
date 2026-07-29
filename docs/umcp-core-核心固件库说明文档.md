# UMCP-Core 核心固件库说明文档

**版本**：2.0.0
**适用范围**：阶段一核心库（含阶段四A/B 扩展后的稳定状态）
**文档定位**：面向核心库使用者和插件开发者，完整说明目录结构、文件功能、对象关系与使用方法。

---

## 一、项目概览

UMCP-Core（Universal Market Coordination Protocol Core）是一个通用双边市场交易协调引擎核心库。它通过七层协议栈（L1-L7）抽象双边市场的全链路：从用户接入、需求资源抽象、匹配调度、交易支付、信任信用、数据智能到治理规则，并以 EventBus 驱动层间解耦。

**核心定位**：
- 核心库只定义抽象基类、接口契约与预置实现，不含任何行业逻辑
- 行业逻辑通过插件包（`plugins/`）注入，按 `domain` 注册到 server
- 抽象基类（`Task` / `Resource` / `MatchStrategy` / `PaymentSchema` / `TrustEngine` / `AccessRule` 等）原则上零修改，所有扩展通过子类化或组合实现

---

## 二、目录结构

```
umcp-core/
├── src/umcp_core/
│   ├── core/                       # 核心抽象（最底层，无内部依赖或仅依赖 domain）
│   │   ├── base.py                 # 参与者抽象：User / Role / Demander / Supplier / PermissionSet
│   │   ├── deal.py                 # 交易记录：Deal / DealStatus
│   │   ├── domain.py               # 领域辅助：DomainTag / Credential / Attachment / SpatioTemporalConstraint
│   │   ├── resource.py             # 资源抽象：Resource / Capability / ResourceStatus
│   │   └── task.py                 # 任务抽象：Task / StandardTask / CustomTask / PackageTask / TaskStatus
│   │
│   ├── events/                     # 事件总线
│   │   ├── bus.py                  # EventBus / Event / InMemoryEventBus
│   │   └── types.py                # EventType 枚举
│   │
│   ├── fsm/                        # 状态机
│   │   ├── base.py                 # StateMachine 抽象基类
│   │   ├── deal_fsm.py             # DealStateMachine（交易状态机）
│   │   └── task_fsm.py             # TaskStateMachine（任务状态机）
│   │
│   ├── layers/                     # 七层协议栈
│   │   ├── l1/access.py            # L1 接入与身份层：AuthProvider / PhoneAuthProvider
│   │   ├── l2/abstraction.py       # L2 需求与资源抽象层：TaskFactory / ResourceRegistry
│   │   ├── l3/matching.py          # L3 匹配与调度层：MatchStrategy / InstantMatch / Bidding / 评分器
│   │   ├── l4/transaction.py       # L4 交易与支付层：PaymentSchema / 6 种支付模式
│   │   ├── l5/trust.py             # L5 信任与信用层：TrustEngine / TrustAggregator / SkillBadge
│   │   ├── l6/intelligence.py      # L6 数据与智能层：IntelligenceModule / 冷启动策略
│   │   └── l7/governance.py        # L7 治理与规则层：RuleEngine / AccessRule / ArbitrationPolicy
│   │
│   ├── protocol/
│   │   └── primitives.py           # 层间协议原语：Request / Confirm / Indication / Response
│   │
│   ├── repositories/               # 仓储接口与内存实现
│   │   ├── interfaces.py           # 6 个 Repository 抽象接口
│   │   └── in_memory.py            # 6 个 InMemory 实现 + InMemoryRepositoryBundle
│   │
│   ├── utils/
│   │   └── helpers.py              # 工具函数：插件 manifest 加载、点分路径导入、命名转换
│   │
│   ├── server.py                   # UMCPServer：协议栈启动入口与组件编排
│   ├── __init__.py                 # 顶层包导出
│   └── py.typed                    # PEP 561 标记
│
├── plugins/                        # 行业插件包（不在核心库内）
├── tests/                          # 核心库测试
├── examples/                       # 示例脚本
└── docs/                           # 文档（specs/plans）
```

### 文件分层依赖关系

```
domain.py（无内部依赖，最底层）
    ↑
base.py ─── resource.py ─── task.py ─── deal.py
    │              │           │           │
    │              └─────┬─────┘           │
    ↓                    ↓                 ↓
layers/l1           layers/l3          fsm/task_fsm
                    layers/l4          fsm/deal_fsm
                    layers/l5
                    layers/l6
                    layers/l7
    │
    ↓
repositories/interfaces.py
    ↑
repositories/in_memory.py
    │
    ↓
server.py（聚合点，依赖几乎所有模块）
```

**循环依赖处理**：
- `core/base.py` 仅在 `TYPE_CHECKING` 下引用 `Credential`，运行时无循环
- `core/task.py` 与 `core/deal.py` 通过函数内延迟导入 `fsm.*`，避免与 fsm 模块的循环依赖

---

## 三、核心模块详解

### 3.1 `core/` — 核心抽象层

#### 3.1.1 `core/domain.py` — 领域辅助对象（最底层模块）

无内部依赖，被几乎所有模块引用。

| 对象 | 类型 | 职责 |
|------|------|------|
| `DomainTag` | `@dataclass(frozen=True)` | 领域标签，`value: str`，`of(value)` 小写化工厂 |
| `Credential` | `@dataclass` | 认证凭据，含 `type`/`token`/`payload`，提供 `phone()`/`email()`/`api_key()` 工厂 |
| `Attachment` | `@dataclass` | 任务附件，含 `name`/`url`/`mime_type`/`size_bytes`/`structured_specs` |
| `SpatioTemporalConstraint` | `@dataclass` | 时空约束，含起终点经纬度/地址、时间窗口 |
| `generate_id(prefix)` | 函数 | 生成带前缀的唯一 ID（`uuid.uuid4().hex[:16]`） |

#### 3.1.2 `core/base.py` — 参与者抽象

定义平台参与者的角色与权限体系。

```
PermissionSet（权限集）
    ↓ 组合
Role（ABC） ─── Demander（ABC, role_type="demander"）
            └── Supplier（ABC, role_type="supplier")
    ↓ 组合多个 Role
User（ABC）
    ├─ user_id, name, roles: dict[str, Role], active_role, metadata
    ├─ authenticate(credential) -> bool   [抽象]
    ├─ add_role(role), switch_role(role_type)
    └─ is_demander(), is_supplier()
```

**对象关系**：
- `User` 组合多个 `Role`（一个用户可同时是需求方和供给方）
- `Role` 持有 `PermissionSet`，通过 `has(permission)` 校验权限
- `Demander` 默认权限：`{"publish_task", "evaluate"}`
- `Supplier` 默认权限：`{"register_resource", "accept_task", "evaluate"}`

#### 3.1.3 `core/resource.py` — 资源抽象

```
ResourceStatus（枚举：OFFLINE/IDLE/BUSY/DISABLED）
Capability（能力单元：type/name/value/verified/expiry）
    ↓ 组合多个 Capability
Resource（ABC）
    ├─ resource_id, supplier_id, domain_tag, status, capabilities, metadata
    ├─ resource_type() -> str                    [抽象]
    ├─ register(), update_status(new_status)
    ├─ validate_capability(cap), has_capability(name)
    └─ is_available()（status=IDLE）
```

**Capability 类型**：`skill` / `certification` / `equipment` / `location`

#### 3.1.4 `core/task.py` — 任务抽象

任务体系是核心库最重要的抽象，支持三种任务类型：

```
TaskStatus（枚举：DRAFT/PUBLISHED/MATCHING/ASSIGNED/IN_PROGRESS/COMPLETED/CANCELLED）
    ↓
Task（ABC）
    ├─ task_id, demander_id, domain_tag, title, description, status
    ├─ attachments, custom_fields, assigned_resource_id
    ├─ _event_bus（可选，绑定后用于 emit 事件）
    ├─ task_type() -> str                        [抽象]
    ├─ bind_event_bus(bus), publish(), cancel(), complete()
    ├─ assign_to(resource_id), start_execution(), add_attachment(attachment)
    └─ _transition(new_status)（通过 TaskStateMachine 校验）
    ↓ 继承
    ├── StandardTask（标准化任务）
    │   ├─ spatio_temporal: SpatioTemporalConstraint
    │   ├─ structured_fields: dict
    │   └─ task_type() = "standard"
    │
    ├── CustomTask（非标准化任务）
    │   ├─ budget_min, budget_max, proposal_requirements
    │   ├─ proposals: list[Proposal]
    │   ├─ submit_proposal(supplier_id, amount, proposal)
    │   └─ task_type() = "custom"
    │
    └── PackageTask（混合任务）
        ├─ standard_sub_tasks: list[StandardTask]
        ├─ custom_sub_task: CustomTask | None
        └─ task_type() = "package"
```

**状态转移图**（由 `TaskStateMachine` 强制）：
```
DRAFT → PUBLISHED → MATCHING → ASSIGNED → IN_PROGRESS → COMPLETED
  ↓         ↓          ↓          ↓            ↓
CANCELLED ← ────────────────────────────────────────
```

**事件发射**：`publish()` / `assign_to()` / `complete()` / `cancel()` 等方法在状态转移后通过 `_emit()` 发射对应 `EventType` 事件到 `_event_bus`。

#### 3.1.5 `core/deal.py` — 交易记录

```
DealStatus（枚举：PENDING/ACTIVE/COMPLETED/DISPUTED/CANCELLED/RESOLVED）
Deal
    ├─ deal_id, task_id, resource_id, demander_id, supplier_id
    ├─ status, final_amount, matched_at, completed_at, metadata
    ├─ activate(), complete(), cancel(), open_dispute(), resolve(outcome)
    └─ _transition(new_status)（通过 DealStateMachine 校验）
```

**状态转移图**：
```
PENDING → ACTIVE → COMPLETED
              ↓
           DISPUTED → RESOLVED → COMPLETED/CANCELLED
任意非终态 → CANCELLED
```

---

### 3.2 `events/` — 事件总线

#### 3.2.1 `events/types.py` — 事件类型

`EventType(str, Enum)` 定义 16 种标准事件：

| 类别 | 事件 |
|------|------|
| 任务生命周期 | `TASK_PUBLISHED` / `TASK_ASSIGNED` / `TASK_COMPLETED` / `TASK_CANCELLED` |
| 匹配 | `MATCH_PROPOSED` / `MATCH_ACCEPTED` / `MATCH_REJECTED` |
| 支付 | `PAYMENT_HELD` / `PAYMENT_CAPTURED` / `PAYMENT_REFUNDED` |
| 信任 | `EVALUATION_SUBMITTED` / `TRUST_UPDATED` |
| 治理与异常 | `ANOMALY_DETECTED` / `RULE_TRIGGERED` / `DISPUTE_OPENED` / `DISPUTE_RESOLVED` |

#### 3.2.2 `events/bus.py` — 事件总线

```
Event
    ├─ type: EventType, source_layer: str, payload: dict
    ├─ timestamp: float, event_id: str
    └─ 自动生成 timestamp 和 event_id

EventHandler = Callable[[Event], None]

EventBus
    ├─ _handlers: dict[EventType, list[EventHandler]]   # 按类型订阅
    ├─ _global_handlers: list[EventHandler]              # 全局订阅
    ├─ _lock: threading.RLock                             # 线程安全
    ├─ _history: list[Event]                              # 事件历史
    ├─ publish(event)                                     # 同步派发
    ├─ subscribe(type_, handler), subscribe_all(handler)
    ├─ unsubscribe(type_, handler)
    └─ history(), clear()

InMemoryEventBus(EventBus)  # 显式命名，便于配置注入
```

**设计要点**：
- 同步派发：`publish()` 直接调用所有匹配 handler，无异步队列
- 线程安全：使用 `RLock` 保护订阅者列表
- 全局订阅：`subscribe_all()` 接收所有事件（用于审计、日志）
- `publish()` 会将事件追加到 `_history`，支持事件回放

---

### 3.3 `fsm/` — 状态机

#### 3.3.1 `fsm/base.py` — 状态机抽象

```
TransitionHandler = Callable[[str, str], None]

StateMachine(ABC)
    ├─ TRANSITIONS: dict[str, set[str]] = {}   # 类属性，子类重写
    ├─ validate_transition(from_status, to_status)  # 非法抛 ValueError
    ├─ can_transition(from_status, to_status) -> bool
    └─ initial_state() -> str                  [抽象]
```

**设计**：状态转移规则以类属性 `TRANSITIONS` 声明，`validate_transition` 在 `Task._transition()` / `Deal._transition()` 中被调用，非法转移立即 fail-fast。

#### 3.3.2 `fsm/task_fsm.py` 与 `fsm/deal_fsm.py`

分别定义 `TaskStateMachine` 和 `DealStateMachine`，各自声明 `TRANSITIONS` 字典（见上文状态转移图）。

---

### 3.4 `layers/` — 七层协议栈

#### 3.4.1 L1 接入与身份层（`layers/l1/access.py`）

```
AuthProvider(ABC)
    ├─ authenticate(credential: Credential) -> User   [抽象]
    ├─ authorize(user, action) -> bool                [抽象]
    └─ revoke(user) -> None                           [抽象]

PhoneAuthProvider(AuthProvider)
    ├─ _users: dict[str, User]
    ├─ _tokens: dict[str, str]
    └─ 内嵌 _DefaultDemander / _DefaultSupplier / _PhoneUser
```

**职责**：验证用户凭据，返回 `User` 实例。`PhoneAuthProvider` 是默认实现，自动注册新用户并赋予默认角色权限。

#### 3.4.2 L2 需求与资源抽象层（`layers/l2/abstraction.py`）

```
TaskFactory(ABC)
    ├─ _builders: dict[str, Any]
    ├─ register_builder(task_type, builder)
    └─ create_task(task_type, demander_id, domain_tag, **kwargs) -> Task  [抽象]

DefaultTaskFactory(TaskFactory)
    └─ 按 _builders 字典反射调用构造器

ResourceRegistry(ABC)
    ├─ register(resource) -> None                     [抽象]
    ├─ unregister(resource_id) -> None                [抽象]
    ├─ find_by_id(resource_id) -> Resource | None     [抽象]
    └─ find_available(domain_tag) -> list[Resource]   [抽象]
```

**职责**：任务工厂支持运行时注册新任务类型；资源注册表支持按 domain 查询可用资源。

#### 3.4.3 L3 匹配与调度层（`layers/l3/matching.py`）

```
MatchResult（@dataclass）
    ├─ task_id, selected_resource_id, bid_amount, candidates: list[str], metadata
    └─ matched -> bool（selected_resource_id 非空）

PreMatchFilter(ABC)  ── 责任链过滤器
    ├─ CredentialFilter       # 资质过滤
    ├─ TrustThresholdFilter   # 信任门槛过滤
    └── CapabilityFilter      # 能力过滤

MatchStrategy(ABC)
    ├─ execute(task, candidates) -> MatchResult       [抽象]
    └─ apply_filters(task, candidates, filters) -> list[Resource]

InstantMatch(MatchStrategy)  ── 系统派单
    ├─ filters: list[PreMatchFilter]
    ├─ scorer: Callable | None
    └─ 按 scorer 降序选第一名，无 scorer 则按资源更新时间降序

DirectPick(MatchStrategy)    ── 需方自选（返回所有候选）

Bidding(MatchStrategy)       ── 招标
    ├─ mode: "reverse_auction" | "proposal_bid"
    ├─ filters, scorer
    └─ 支持 awaiting_proposals 与 auto_selected 两种元信息
    ├── ReverseAuction(Bidding)   # 逆向拍卖
    └── ProposalBid(Bidding)      # 方案竞标

SkillMatchScorer             # 技能匹配评分器（__call__(task, resource) -> float）
CompositeBidScorer           # 多维报价评分器（price/delivery/trust 加权）
```

**命名兼容别名**（CodeWiki 9.2）：
- `NearestMatch = InstantMatch`
- `AuctionMatch = Bidding`

#### 3.4.4 L4 交易与支付层（`layers/l4/transaction.py`）

```
PaymentStatus（枚举：CREATED/HELD/CAPTURED/REFUNDED/FAILED）

PaymentOrder（@dataclass）
    ├─ order_id, deal_id, total_amount, commission, supplier_amount
    ├─ status, metadata, created_at
    └─ settle_split()（supplier_amount = total_amount - commission）

CommissionRule(ABC) ── FlatCommissionRule（默认 0.20）
RefundPolicy(ABC)   ── FullRefundPolicy

PaymentSchema(ABC)
    ├─ calculate(task, deal) -> PaymentOrder          [抽象]
    ├─ hold(order), capture(order), refund(order)     [抽象]
    │
    ├── FixedPrice           # 一口价
    ├── DynamicPricing       # 动态计价（surge_factor）
    ├── Prepaid              # 预付费（hold 即扣款）
    ├── Milestone            # 里程碑分期
    ├── Hourly               # 计时（hourly_rate）
    └── InstallmentPayment   # 订金+尾款（30%/70%）
        ├─ hold_deposit(order), capture_deposit(order), capture_balance(order)
        └─ PaymentOrder.metadata: deposit_amount/balance_amount/deposit_status/balance_status
```

**设计要点**：6 种支付模式覆盖双边市场常见场景；`InstallmentPayment` 扩展 `PaymentOrder.metadata` 跟踪订金/尾款状态。

#### 3.4.5 L5 信任与信用层（`layers/l5/trust.py`）

```
Evaluation（@dataclass）
    └─ evaluator_id, evaluatee_id, task_id, ratings: dict[str, float], comment, created_at

TrustProfile（@dataclass）
    ├─ user_id, dimension_scores: dict[str, float], overall_score, last_updated
    ├─ update_dimension(dimension, score)  # 自动重算 overall_score
    └─ get_score(dimension=None) -> float

RiskWeight（@dataclass）
    └─ weights: dict[str, float], weight_of(dimension) -> float（默认 1.0）

CredentialValidator(ABC) ── SimpleCredentialValidator（仅检查 token 非空）

TrustEngine(ABC)
    ├─ evaluate(user_id, context=None) -> TrustProfile   [抽象]
    └─ record_evaluation(evaluation) -> TrustProfile     [抽象]

WeightedSumTrustEngine(TrustEngine)
    ├─ dimensions: list[str], risk_weight: RiskWeight, _profiles: dict[str, TrustProfile]
    └─ 评价更新策略：简单移动平均（新旧各占 50%）

SkillBadge
    └─ grant(user_id, badge), revoke(user_id, badge), list_badges(user_id)

TrustAggregator(ABC)                    # 跨 domain 信任聚合策略
    └─ aggregate(user_id, engines: dict[str, TrustEngine]) -> float

MeanTrustAggregator(TrustAggregator)    # 算术平均（默认实现）
```

**命名兼容别名**（CodeWiki 10.1）：
- `SimpleRating = WeightedSumTrustEngine` ≈ `RatingAggregator`
- `CredibilityScore = WeightedSumTrustEngine` ≈ `CredibilityModel`
- `BadgeSystem = SkillBadge`

**跨域聚合**（阶段四B 新增）：`TrustAggregator` 支持将多个 domain 的 `TrustEngine.evaluate(user_id).overall_score` 聚合为单一分数，默认算术平均，可通过 `set_trust_aggregator()` 注入自定义策略。

#### 3.4.6 L6 数据与智能层（`layers/l6/intelligence.py`）

```
Prediction（@dataclass）       ── target, value, confidence, metadata
PredictionContext（@dataclass）── domain, location, time_window, extra
AnomalyReport（@dataclass）    ── anomaly_type, severity(low/medium/high), description, context

ColdStartStrategy(ABC) ── DefaultColdStartStrategy
    └─ default_value(target) -> float
    └─ 默认值: {"demand": 1.0, "price": 1.0, "eta": 600.0}

IntelligenceModule(ABC)
    ├─ predict(context) -> Prediction                    [抽象]
    ├─ recommend(task, pool) -> list[Resource]           [抽象]
    └─ detect_anomaly(event) -> AnomalyReport | None     [抽象]

NoopIntelligenceModule(IntelligenceModule)  # 空实现占位符
```

**职责**：行业可选层，用于需求预测、资源推荐、异常检测。核心库提供 `NoopIntelligenceModule` 作为默认占位符。

#### 3.4.7 L7 治理与规则层（`layers/l7/governance.py`）

```
AccessRule(ABC)
    └─ check(user, task) -> bool                         [抽象]

ExpressionAccessRule(AccessRule)
    ├─ expression: str  # 支持 hasCredential('xxx')、trustScore >= N、&& / ||
    ├─ bind_trust_engine_lookup(lookup)  # 幂等注入 domain→TrustEngine 路由
    └─ check(user, task) -> bool

RuleContext（@dataclass）
    ├─ user, task, trust_engine_for_domain: Callable | None
    ├─ has_credential(name) -> bool
    └─ trust_score -> float  # 按 task.domain_tag 路由到 TrustEngine，回退到 user.metadata

Dispute（@dataclass）         ── dispute_id, deal_id, initiator_id, respondent_id, reason, evidence, status
ArbitrationResult（@dataclass）── dispute_id, outcome, refund_amount, penalty, reason

ArbitrationPolicy(ABC) ── SimpleArbitrationPolicy（默认判决发起人胜诉）
ComplianceModule(ABC)  ── NoopComplianceModule

RuleEngine
    ├─ _access_rules: list[AccessRule]                   # 全局准入规则
    ├─ _domain_access_rules: dict[str, list[AccessRule]] # 按 domain 隔离的规则
    ├─ _domain_trust_engines: dict[str, TrustEngine]     # domain→TrustEngine 映射
    ├─ _arbitration_policy: ArbitrationPolicy
    ├─ _compliance: ComplianceModule
    │
    ├─ add_access_rule(rule, domain=None)
    ├─ register_trust_engine(domain, engine)
    ├─ set_arbitration_policy(policy), set_compliance_module(module)
    ├─ check_access(user, task) -> bool
    │   └─ 向 ExpressionAccessRule 注入 trust_engine_lookup（幂等）
    ├─ arbitrate(dispute) -> ArbitrationResult
    ├─ audit(deal) -> bool
    └─ get_required_compliances(task) -> list[str]
```

**设计要点**：
- `ExpressionAccessRule` 支持声明式表达式（`hasCredential('business_license') && trustScore >= 4.0`），通过 `eval` 求值（禁用 builtins）
- `RuleContext.trust_score` 按 `task.domain_tag` 路由到对应 domain 的 `TrustEngine`，未注入时回退到 `user.metadata['trust_score']`（向后兼容）
- `RuleEngine.check_access` 在首次调用时向 `ExpressionAccessRule` 幂等注入 `trust_engine_lookup`，使声明式规则也能按 domain 路由信任分

---

### 3.5 `protocol/primitives.py` — 层间协议原语

定义七层协议栈的层间通信原语（OSI 风格）：

```
LayerId(str, Enum)  ── L1_ACCESS ~ L7_GOVERNANCE

Request(Generic[T])     ── 上层→下层：target_layer, source_layer, operation, payload
Confirm(Generic[R])     ── 下层→上层：source_layer, target_layer, request_id, success, result, error
Indication(Generic[E])  ── 下层主动推送：source_layer, target_layer, event_type, payload
Response                ── 上层回应指示：source_layer, target_layer, indication_id, success, message

LayerProtocol(ABC)
    ├─ layer_id: LayerId
    ├─ send_request(target, operation, payload) -> Request
    ├─ send_indication(target, event_type, payload) -> Indication
    ├─ on_request(request) -> Confirm
    └─ on_indication(indication) -> Response
```

**说明**：当前阶段各层主要通过 EventBus 解耦，`LayerProtocol` 作为未来扩展的层间强类型协议接口预留。

---

### 3.6 `repositories/` — 仓储接口与实现

#### 3.6.1 `repositories/interfaces.py` — 6 个 Repository 接口

| 接口 | 主要方法 | 职责 |
|------|---------|------|
| `TaskRepository` | `save` / `find_by_id` / `find_by_demander` / `find_by_status` / `update_status` | 任务持久化 |
| `ResourceRepository` | `save` / `find_by_id` / `find_by_supplier` / `find_available(domain_tag)` / `update_status` | 资源持久化 |
| `DealRepository` | `save` / `find_by_id` / `find_by_task` / `find_by_supplier` | 交易持久化 |
| `UserRepository` | `save` / `find_by_id` / `find_by_name` | 用户持久化 |
| `TrustRepository` | `save_profile` / `find_profile` / `save_evaluation` / `find_evaluations` | 信任数据持久化 |
| `EventRepository` | `append(event)` / `replay(aggregate_id)` | 事件持久化与回放 |

#### 3.6.2 `repositories/in_memory.py` — 内存实现

```
InMemoryTaskRepository(TaskRepository)        ── 字典 + RLock
InMemoryResourceRepository(ResourceRepository)
InMemoryDealRepository(DealRepository)
InMemoryUserRepository(UserRepository)        ── 维护 _users + _by_name 双索引
InMemoryTrustRepository(TrustRepository)      ── 维护 _profiles + _evaluations
InMemoryEventRepository(EventRepository)      ── replay 支持 task_id/deal_id/user_id 过滤

InMemoryRepositoryBundle
    ├─ task_repo, resource_repo, deal_repo
    ├─ user_repo, trust_repo, event_repo
    └─ 一次性注入所有内存仓储
```

**设计要点**：接口与实现分离，生产环境可注入 MySQL/PostgreSQL 实现，开发调试用内存实现。

---

### 3.7 `utils/helpers.py` — 工具函数

| 函数 | 职责 |
|------|------|
| `load_plugin_manifest(plugin_path)` | 加载 plugin.json |
| `import_class(dotted_path)` | 根据点分路径导入类（如 `"umcp_core.layers.l3.matching.InstantMatch"`） |
| `camel_to_snake(name)` | 驼峰转蛇形 |
| `snake_to_camel(name)` | 蛇形转驼峰 |

---

### 3.8 `server.py` — UMCPServer 编排入口

`UMCPServer` 是核心库与行业应用的聚合点，负责组件注入、插件加载与协议栈启动。

#### 3.8.1 核心属性

```
UMCPServer
    │
    ├── 横切组件
    │   ├── event_bus: EventBus
    │   └── rule_engine: RuleEngine
    │
    ├── 各层组件（默认值）
    │   ├── auth_provider: AuthProvider = PhoneAuthProvider()
    │   ├── task_factory: DefaultTaskFactory
    │   ├── resource_registry: ResourceRegistry | None
    │   ├── match_strategy: MatchStrategy | None
    │   ├── payment_schema: PaymentSchema | None
    │   ├── trust_engine: TrustEngine | None
    │   └── intelligence_module: IntelligenceModule = NoopIntelligenceModule()
    │
    ├── 仓储（默认 None）
    │   └── task_repo / resource_repo / deal_repo / user_repo / trust_repo / event_repo
    │
    ├── 按 domain 索引的策略注册表（多插件并存）
    │   ├── _match_strategies: dict[str, MatchStrategy]
    │   ├── _payment_schemas: dict[str, PaymentSchema]
    │   └── _trust_engines: dict[str, TrustEngine]
    │
    ├── 跨 domain 信任聚合器
    │   └── _trust_aggregator: TrustAggregator = MeanTrustAggregator()
    │
    └── 已加载插件
        └── _plugins: list[PluginDescriptor]
```

#### 3.8.2 关键方法

| 类别 | 方法 | 说明 |
|------|------|------|
| 仓储配置 | `use_in_memory_repositories()` | 使用内存仓储（开发调试） |
| 仓储配置 | `set_repositories(...)` | 注入自定义仓储（生产环境） |
| 层组件注入 | `set_match_strategy(strategy)` 等 | 注入单值组件（单插件模式） |
| 按 domain 注册 | `register_match_strategy(domain, strategy)` | 按 domain 注册（多插件模式） |
| 按 domain 查询 | `match_strategy_for(domain)` | 按 domain 查询，未命中回退单值 |
| 信任聚合 | `register_trust_engine(domain, engine)` | 同步到 RuleEngine |
| 信任聚合 | `aggregate_trust_score(user_id)` | 跨 domain 聚合 trust_score |
| 任务工厂 | `register_task_type(task_type, builder)` | 注册任务类型 |
| 插件加载 | `load_plugin(plugin_path)` | 加载插件（文件路径/目录/模块名） |
| 启停 | `start()` / `stop()` | 启动/停止协议栈 |

#### 3.8.3 插件 manifest 字段

`_apply_manifest(descriptor)` 解析以下 manifest 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `domain` | `str` 或 `list[str]` | 领域标签，统一小写化 |
| `task_types` | `list[str]` | 任务类点分路径列表 |
| `match_strategy` | `str` | 匹配策略类点分路径 |
| `payment_schema` | `str` | 支付模式类点分路径 |
| `trust_engine` | `str` | 信任引擎类点分路径 |
| `access_rule_expression` | `str` | 准入规则表达式字符串 |

**启动校验**：`start()` 调用 `_validate_required_components()`，必须具备 `match_strategy`、`payment_schema`、`trust_engine`、`task_repo`，否则抛 `RuntimeError`。

#### 3.8.4 事件审计

构造时自动订阅全局事件审计：
```python
self.event_bus.subscribe_all(self._audit_event)
```
`_audit_event` 对 `ANOMALY_DETECTED` / `RULE_TRIGGERED` / `DISPUTE_OPENED` 事件打印审计日志。

---

## 四、对象关系总览

### 4.1 核心实体关系

```
User ──持有──→ Role ──持有──→ PermissionSet
  │
  ├──创建──→ Task ──包含──→ Attachment
  │            │
  │            ├──绑定──→ EventBus
  │            └──状态机──→ TaskStateMachine
  │
  ├──注册──→ Resource ──持有──→ Capability
  │              │
  │              └──状态机──→ ResourceStatus
  │
  └──参与──→ Deal ──状态机──→ DealStateMachine
                │
                └──关联──→ PaymentOrder ──策略──→ PaymentSchema
```

### 4.2 七层协议栈协作流

```
用户接入（L1 AuthProvider）
    ↓ 认证成功返回 User
需求发布（L2 TaskFactory 创建 Task）
    ↓ Task 进入 MATCHING 状态
资源匹配（L3 MatchStrategy.execute）
    ↓ MatchResult.selected_resource_id
交易创建（L4 PaymentSchema.calculate）
    ↓ PaymentOrder 生成
信任评估（L5 TrustEngine.evaluate）
    ↓ TrustProfile 影响下次匹配
智能推荐（L6 IntelligenceModule.recommend）
    ↓ 补充候选资源
治理审计（L7 RuleEngine.check_access）
    ↓ 准入规则校验
全流程事件通过 EventBus 解耦
```

---

## 五、使用方法

### 5.1 最小可用示例（单插件模式）

```python
from umcp_core.server import UMCPServer

# 1. 创建服务器并使用内存仓储
server = UMCPServer()
server.use_in_memory_repositories()

# 2. 加载行业插件
server.load_plugin("plugins/ride_hailing/plugin.json")

# 3. 启动协议栈
server.start()

# 4. 创建任务、匹配资源、创建交易...
# （具体业务逻辑由插件实现）
```

### 5.2 多插件并存模式

```python
server = UMCPServer()
server.use_in_memory_repositories()

# 加载多个插件，各自注册到不同 domain
server.load_plugin("plugins/ride_hailing/plugin.json")       # domain=ride
server.load_plugin("plugins/escort_driving/plugin.json")     # domain=escort
server.load_plugin("plugins/group_buying/plugin.json")       # domain=group_buying

server.start()

# 按 domain 查询策略
ride_strategy = server.match_strategy_for("ride")
gb_schema = server.payment_schema_for("group_buying")

# 跨 domain 聚合信任分
aggregate_score = server.aggregate_trust_score("user_001")
```

### 5.3 自定义组件注入

```python
from umcp_core.layers.l3 import InstantMatch, SkillMatchScorer
from umcp_core.layers.l4 import FixedPrice, FlatCommissionRule
from umcp_core.layers.l5 import WeightedSumTrustEngine, RiskWeight
from umcp_core.layers.l7 import RuleEngine, ExpressionAccessRule

server = UMCPServer()

# 注入自定义匹配策略
server.set_match_strategy(InstantMatch(scorer=SkillMatchScorer()))

# 注入自定义支付模式
server.set_payment_schema(FixedPrice(commission_rule=FlatCommissionRule(rate=0.15)))

# 注入自定义信任引擎（多维评分）
engine = WeightedSumTrustEngine(
    dimensions=["delivery", "quality", "service", "cost_performance"],
    risk_weight=RiskWeight(weights={"delivery": 1.5, "quality": 1.2}),
)
server.set_trust_engine(engine)

# 添加准入规则
server.rule_engine.add_access_rule(
    ExpressionAccessRule("hasCredential('business_license') && trustScore >= 4.0")
)
```

### 5.4 自定义仓储实现

```python
from umcp_core.repositories.interfaces import (
    TaskRepository, ResourceRepository, DealRepository,
    UserRepository, TrustRepository, EventRepository,
)

class MysqlTaskRepository(TaskRepository):
    def save(self, task):
        # 实现 MySQL 持久化
        ...
    # 实现其他抽象方法...

# 注入到 server
server.set_repositories(
    task_repo=MysqlTaskRepository(),
    resource_repo=MysqlResourceRepository(),
    deal_repo=MysqlDealRepository(),
    user_repo=MysqlUserRepository(),
    trust_repo=MysqlTrustRepository(),
    event_repo=MysqlEventRepository(),
)
```

### 5.5 事件订阅

```python
from umcp_core.events.types import EventType

# 订阅特定事件
def on_task_published(event):
    print(f"任务已发布: {event.payload}")

server.event_bus.subscribe(EventType.TASK_PUBLISHED, on_task_published)

# 全局订阅（审计）
def audit_all(event):
    print(f"[AUDIT] {event.type}: {event.payload}")

server.event_bus.subscribe_all(audit_all)
```

### 5.6 开发行业插件

插件目录结构：
```
plugins/my_industry/
├── plugin.json              # 插件清单
├── __init__.py              # PLUGIN_MANIFEST + register_plugin(server)
├── tasks.py                 # 任务子类
├── resources.py             # 资源子类
├── matching.py              # 匹配策略
├── payment.py               # 支付模式
├── trust.py                 # 信任引擎
└── tests/
    └── test_plugin.py
```

`plugin.json` 示例：
```json
{
    "name": "my_industry",
    "version": "1.0.0",
    "domain": "my_industry",
    "task_types": ["plugins.my_industry.tasks.MyTask"],
    "match_strategy": "plugins.my_industry.matching.MyMatchStrategy",
    "payment_schema": "plugins.my_industry.payment.MyPaymentSchema",
    "trust_engine": "plugins.my_industry.trust.MyTrustEngine",
    "access_rule_expression": "hasCredential('my_cert') && trustScore >= 3.0"
}
```

---

## 六、设计要点总结

1. **七层协议栈**：L1 接入 → L2 抽象 → L3 匹配 → L4 交易 → L5 信任 → L6 智能 → L7 治理，L7 是横切的"大脑皮层"，与其他层交叉
2. **状态机驱动**：Task 与 Deal 各有独立状态机，通过 `validate_transition` 强制校验，非法转移 fail-fast
3. **事件总线解耦**：各层通过 EventBus 通信，L6 异常检测与 L7 规则审计通过订阅事件实现
4. **依赖注入**：Repository 接口与实现分离，支持内存/MySQL/PostgreSQL 等多种后端
5. **插件机制**：通过 `plugin.json` 反射加载行业实现类，按 domain 注册策略支持多插件并存
6. **多 domain 信任聚合**：`TrustAggregator` 抽象支持跨 domain 信任分聚合（默认算术平均）
7. **抽象基类零修改原则**：所有扩展通过子类化或组合实现，核心库演进不破坏现有插件
8. **命名兼容**：提供 CodeWiki 9.2/10.1 命名别名，行为与原类一致
9. **延迟导入避免循环依赖**：`core/base.py` 使用 `TYPE_CHECKING`，`core/task.py`/`core/deal.py` 使用函数内延迟导入

---

## 七、附录：命名兼容别名

| 别名 | 等价类 | 来源 |
|------|--------|------|
| `NearestMatch` | `InstantMatch` | CodeWiki 9.2 |
| `AuctionMatch` | `Bidding` | CodeWiki 9.2 |
| `SimpleRating` | `WeightedSumTrustEngine` | CodeWiki 10.1 |
| `CredibilityScore` | `WeightedSumTrustEngine` | CodeWiki 10.1 |
| `RatingAggregator` | `SimpleRating` | CodeWiki 10.1 |
| `CredibilityModel` | `CredibilityScore` | CodeWiki 10.1 |
| `BadgeSystem` | `SkillBadge` | CodeWiki 10.1 |

> 这些别名仅为与设计文档命名保持兼容，行为与等价类完全一致，实际编码建议直接使用主名称。

## 阶段五B：HTTP 传输层（transport/ 子包）

将 UMCPServer 暴露为 FastAPI 应用，提供 RESTful API + WebSocket。

### 目录结构

- `transport/__init__.py`：导出 create_app
- `transport/app.py`：FastAPI 应用工厂（create_app(server, config)）
- `transport/config.py`：TransportConfig + from_env
- `transport/deps.py`：依赖注入（get_current_user / get_server / get_jwt_service）
- `transport/auth.py`：JwtService（签发/校验/吊销）+ user_from_claims
- `transport/errors.py`：ApiError 异常体系 + register_exception_handlers
- `transport/schemas.py`：Pydantic 统一信封 + 分页模型
- `transport/ws.py`：ConnectionManager + EventBus→WS 桥接
- `transport/routers/`：8 个资源域 router（auth/tasks/resources/matches/deals/trust/events/health）
- `transport/__main__.py`：应用入口（python -m umcp_core.transport）

### 启动方式

```bash
export UMCP_JWT_SECRET=your-secret
python -m umcp_core.transport
```

或编程式：

```python
from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig

server = UMCPServer()
server.use_in_memory_repositories()
server.load_plugin("plugins/ride_hailing/plugin.json")
server.start()

config = TransportConfig(jwt_secret="secret")
app = create_app(server, config)
# 用 uvicorn 启动：uvicorn.run(app, host="0.0.0.0", port=8000)
```
