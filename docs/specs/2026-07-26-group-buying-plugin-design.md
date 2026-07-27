# 阶段三：小微单位集采服务插件设计规格

## 目标

通过实现小微单位集采服务行业插件（多买家需求聚合 → 反向竞价招标 → 多供应商报价 → 选标成交 → 履约 → 双向评价），验证 UMCP 核心抽象的通用性——同一套 umcp-core 能否通过"扩展预置策略、不修改抽象基类"的方式承载与网约车（C2C 实时按距离匹配）、陪驾（C2C 实时按技能匹配）差异足够大的第三个行业：C2B 反向竞价 + N-to-1 需求聚合 + 混合任务编排 + 分期付款。

## 业务模式

**反向竞价/招标 + 双层模式：**

```
第一层（需求聚合）：N 个小微单位 → 各自发 BuyerTask（CustomTask） → BrokerAgent 聚合
第二层（反向竞价）：BrokerAgent 发起 TenderTask（PackageTask） → M 个供应商报价 → 系统选优
```

**标的物：** 混合（商品 + 服务），TenderTask 包含 1 个商品子任务 + 1 个服务子任务，验证 PackageTask 编排能力。

## 架构

### 双层交易闭环（5 个阶段）

```
阶段 0：需求意向聚合
─────────────────────
N 个 BuyerTask（CustomTask） ──→ BrokerAgent 聚合 ──→ 1 个 TenderTask（PackageTask）
  （用户：品类+数量+预算）         （虚拟中间人）        （含商品子任务+服务子任务）

阶段 1：反向竞价
─────────────────────
TenderTask（招标中） ←── M 个 SupplierResource 提交 Bid（价格+交期+方案）
                              ↓
                    TenderBidScorer 评分排序
                              ↓
                    选最优 Bid → assign_to(supplier)

阶段 2：支付托管（订金+尾款分期）
─────────────────────
Deal（订单） → 订金托管（HELD）→ 服务方备货 → 订金 CAPTURED
            → 履约完成 → 尾款结算 → 尾款 CAPTURED

阶段 3：履约（商品配送+服务执行）
─────────────────────
商品子任务：ASSIGNED → IN_PROGRESS → COMPLETED
服务子任务：ASSIGNED → IN_PROGRESS → COMPLETED
两个子任务都完成 → TenderTask.complete()

阶段 4：双向评价
─────────────────────
N 个买家 → 评供应商（交期/质量/服务/性价比 4 维）
供应商 → 评买家群体（结算及时性/配合度 2 维）
```

### 核心库改动（最小化）

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增 `CompositeBidScorer` | `src/umcp_core/layers/l3/matching.py` | 通用多维度报价评分器（价格分+交期分+信誉分加权），与 `SkillMatchScorer` 同级 |
| 新增 `InstallmentPayment` | `src/umcp_core/layers/l4/transaction.py` | 通用分期付款策略（订金+尾款两期），与 `Hourly`/`DynamicPricing` 同级 |
| **不修改** | `src/umcp_core/core/` | Task/Resource/Deal 抽象基类零改动 |
| **不修改** | `src/umcp_core/layers/l3/matching.py` 中已有 `ReverseAuction`/`Bidding` | 直接复用 |
| **不修改** | `src/umcp_core/events/types.py` | 复用 TASK_PUBLISHED/TASK_ASSIGNED/TASK_COMPLETED |

## 核心库新增组件

### CompositeBidScorer（通用报价评分器）

**位置：** `src/umcp_core/layers/l3/matching.py`（追加在 SkillMatchScorer 之后）

**接口契约：**

```python
class CompositeBidScorer:
    """通用多维度报价评分器（预置）。

    基于 Bid 的价格、交期、信誉三维度加权评分。
    价格越低分越高，交期越短分越高，信誉越高分越高。
    与 InstantMatch 的 reverse=True 配合实现高分优先。
    """

    def __init__(
        self,
        price_weight: float = 0.5,
        delivery_weight: float = 0.3,
        trust_weight: float = 0.2,
    ) -> None: ...

    def __call__(self, task: Task, resource: Resource) -> float:
        # 从 resource.metadata["bid"] 读取 {price, delivery_days, trust_score}
        # 归一化后加权求和
```

**评分公式：**
- 价格分 = (max_price - bid_price) / (max_price - min_price)，归一化到 [0, 1]
- 交期分 = (max_delivery - bid_delivery) / (max_delivery - min_delivery)，归一化到 [0, 1]
- 信誉分 = bid_trust / 5.0（假设信誉满分 5.0）
- 综合分 = 价格分 × price_weight + 交期分 × delivery_weight + 信誉分 × trust_weight

**为何放核心库：** 多维度报价评分是通用能力，任何招标场景（集采、外包、咨询）都可复用。与 `SkillMatchScorer` 同级。

**归一化基准：** 价格和交期的 max/min 由当前批次所有供应商的 bid 决定。当只有 1 个 bid 时（无对比），价格分和交期分均为 1.0（中性满分）。

### InstallmentPayment（通用分期付款策略）

**位置：** `src/umcp_core/layers/l4/transaction.py`（追加在 Hourly 之后）

**接口契约：**

```python
class InstallmentPayment(PaymentSchema):
    """分期付款模式（预置）。

    支持订金+尾款两期结算：
    - calculate() 返回单个 PaymentOrder，total_amount = 全款
    - deposit_ratio 控制订金比例（如 0.3 = 30% 订金）
    - hold_deposit() 仅托管订金部分
    - capture_deposit() 扣订金
    - capture_balance() 扣尾款（履约完成后）
    """

    def __init__(
        self,
        deposit_ratio: float = 0.3,
        commission_rule: CommissionRule | None = None,
    ) -> None: ...

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder: ...
    def hold_deposit(self, order: PaymentOrder) -> None: ...
    def capture_deposit(self, order: PaymentOrder) -> None: ...
    def capture_balance(self, order: PaymentOrder) -> None: ...
```

**PaymentOrder 扩展（通过 metadata，不新增字段）：**
- `order.metadata["deposit_amount"]` = 订金金额
- `order.metadata["balance_amount"]` = 尾款金额
- `order.metadata["deposit_status"]` = "none" / "held" / "captured"
- `order.metadata["balance_status"]` = "none" / "captured"

**为何放核心库：** 分期付款是通用支付模式（集采订金尾款、装修分期、外包里程碑付款），与 `Hourly`/`DynamicPricing` 同级。

**状态前置校验：**
- `hold_deposit()` 要求 `deposit_status == "none"`，否则抛 RuntimeError
- `capture_deposit()` 要求 `deposit_status == "held"`，否则抛 RuntimeError
- `capture_balance()` 要求 `deposit_status == "captured"` 且 `balance_status == "none"`，否则抛 RuntimeError
- `capture_balance()` 成功后 `balance_status = "captured"` 且 `order.status = CAPTURED`

## 集采插件包组件

### BuyerTask（采购需求意向）

**位置：** `plugins/group_buying/tasks.py`

```python
class BuyerTask(CustomTask):
    """采购需求意向（非标准化任务）。

    单个小微单位的采购需求，作为聚合原料。
    继承 CustomTask，携带预算范围。
    """
    _task_type_name = "buyer"

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        category: str,              # 品类（如 "空调"、"保洁"）
        quantity: int,              # 数量
        budget_max: float,          # 单件预算上限
        spec_requirements: list[str] | None = None,  # 规格要求
        **kwargs: Any,
    ) -> None: ...
```

**字段约定：**
- `custom_fields["category"]` = 品类
- `custom_fields["quantity"]` = 数量
- `custom_fields["spec_requirements"]` = 规格要求列表
- `budget_min` / `budget_max`（继承自 CustomTask）

### TenderTask（聚合招标任务）

**位置：** `plugins/group_buying/tasks.py`

```python
class TenderTask(PackageTask):
    """聚合招标任务（混合任务）。

    虚拟中间人聚合多个 BuyerTask 后发起的招标任务。
    包含 1 个商品子任务（StandardTask）+ 1 个服务子任务（CustomTask）。
    """
    _task_type_name = "tender"

    def __init__(
        self,
        demander_id: str,           # 虚拟中间人 ID
        domain_tag: DomainTag,
        category: str,
        total_quantity: int,         # 聚合后总数量
        target_unit_price: float,    # 目标单价（加权平均预算）
        buyer_task_ids: list[str],   # 聚合的 BuyerTask ID 列表
        **kwargs: Any,
    ) -> None: ...

    def complete(self) -> None:
        # 前置校验：所有子任务必须 COMPLETED
        for sub in self.standard_sub_tasks:
            if sub.status != TaskStatus.COMPLETED:
                raise RuntimeError(f"子任务 {sub.task_id} 未完成")
        if self.custom_sub_task and self.custom_sub_task.status != TaskStatus.COMPLETED:
            raise RuntimeError("服务子任务未完成")
        super().complete()
```

**字段约定：**
- `custom_fields["category"]` / `["total_quantity"]` / `["target_unit_price"]`
- `custom_fields["buyer_task_ids"]` = 聚合来源（用于事件通知买家）
- `custom_fields["bid_deadline"]` = 投标截止时间
- `standard_sub_tasks[0]` = 商品子任务（StandardTask，含 SKU/数量/配送地址）
- `custom_sub_task` = 服务子任务（CustomTask，含服务要求/工期/验收标准）

**完成判定逻辑：** 放在插件层（TenderTask 覆写 `complete()`），不修改 PackageTask 基类。

### SupplierResource（供应商资源）

**位置：** `plugins/group_buying/resources.py`

```python
class SupplierResource(Resource):
    """供应商资源（可投标单元）。

    代表供应商+商品SKU+服务能力的组合。
    """
    _resource_type = "supplier"

    def __init__(
        self,
        supplier_id: str,
        domain_tag: DomainTag,
        supplier_name: str,
        product_sku: str,            # 商品 SKU
        service_capability: list[str],  # 服务能力标签（如 ["delivery", "installation"]）
        trust_score: float = 3.0,    # 初始信誉分
        capabilities: list[Capability] | None = None,
        **kwargs: Any,
    ) -> None: ...
```

**字段约定：**
- `metadata["supplier_name"]` / `["product_sku"]` / `["service_capability"]`
- `metadata["trust_score"]` = 信誉分（供 CompositeBidScorer 读取）
- `metadata["bid"]` = 提交报价后写入 `{price, delivery_days, proposal}`

**默认能力：** 包含 `business_license`（营业执照，准入规则要求）。

### BrokerAgent（虚拟中间人）

**位置：** `plugins/group_buying/broker.py`

```python
class BrokerAgent:
    """虚拟中间人：聚合 BuyerTask → 发起 TenderTask。

    职责：
    1. 接收同品类 BuyerTask
    2. 按品类+时间窗聚合需求
    3. 聚合数量达到阈值后创建 TenderTask
    4. 通知所有参团买家
    """

    def __init__(
        self,
        server: "UMCPServer",
        broker_user_id: str = "broker_001",
        aggregation_threshold: int = 3,  # 最少多少个 BuyerTask 才能开标
    ) -> None: ...

    def submit_buyer_task(self, task: BuyerTask) -> None:
        """接收买家需求意向，按品类缓冲聚合。"""

    def try_aggregate(self, category: str) -> TenderTask | None:
        """尝试聚合指定品类的待处理需求。"""

    def notify_buyers(self, tender: TenderTask, event_type: str) -> None:
        """通知所有参团买家招标进展。"""
```

**设计要点：**
- BrokerAgent 是**插件层组件**，不下沉到核心库（业务策略，非通用能力）
- 通过显式调用 `submit_buyer_task` + `try_aggregate` 工作（不依赖事件总线异步订阅，便于测试）
- `broker_user_id` 作为 TenderTask 的 `demander_id`
- 同品类 BuyerTask 累积达到 `aggregation_threshold` 时才能聚合
- 聚合后该批 BuyerTask 从缓冲池移除（防重复聚合）
- 不同品类独立缓冲池

### TenderBidScorer（行业评分器）

**位置：** `plugins/group_buying/scoring.py`

```python
class TenderBidScorer:
    """集采行业报价评分器（行业策略）。

    组合通用 CompositeBidScorer 与集采特有逻辑：
    1. 资质硬约束：无 business_license 直接返回 -1.0
    2. 服务能力匹配：供应商必须覆盖招标要求的服务标签
    3. 通用报价评分（价格+交期+信誉加权）
    """

    def __init__(
        self,
        required_service_tags: list[str] | None = None,
        composite_scorer: CompositeBidScorer | None = None,
    ) -> None: ...

    def __call__(self, task: Task, resource: Resource) -> float: ...
```

**评分逻辑：**
1. 资质硬约束：`resource.has_capability("business_license")` 为 False → 返回 -1.0
2. 服务能力匹配：`required_service_tags` 中每个标签都必须在 `resource.metadata["service_capability"]` 中，否则返回 -1.0
3. 通用报价评分：调用 `CompositeBidScorer(task, resource)`，返回其结果

**为何不放核心库：** 服务能力标签匹配是集采特有逻辑，其他行业（网约车/陪驾）无此概念。

### PLUGIN_MANIFEST 与 register_plugin

**位置：** `plugins/group_buying/__init__.py`

```python
PLUGIN_MANIFEST = {
    "name": "group-buying",
    "version": "1.0.0",
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

def register_plugin(server: "UMCPServer") -> None:
    from umcp_core.layers.l3 import CredentialFilter, ReverseAuction
    from umcp_core.layers.l4 import FlatCommissionRule, InstallmentPayment
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from group_buying.scoring import TenderBidScorer

    server.set_match_strategy(
        ReverseAuction(
            scorer=TenderBidScorer(),
            filters=[CredentialFilter(required_credentials=["business_license"])],
        )
    )
    server.set_payment_schema(
        InstallmentPayment(
            deposit_ratio=PLUGIN_MANIFEST["deposit_ratio"],
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        )
    )
    server.set_trust_engine(
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"])
    )
```

**配置说明：**
- 抽成 5%（集采低毛利）
- 订金 30%（行业惯例）
- 信任维度 4 维：delivery（交期）/quality（质量）/service（服务）/cost_performance（性价比）
- 准入：营业执照 + 信誉分 ≥ 3.0

## 交易流程时序

### 完整交易时序

```
买家A ──┐
买家B ──┼──→ BrokerAgent.submit_buyer_task() ──→ 缓冲池（按品类）
买家C ──┘                                              │
                                                       ↓
                                    try_aggregate() 达到阈值(3)
                                                       │
                                                       ↓
                              ┌────────────────────────────────────┐
                              │ 创建 TenderTask（PackageTask）       │
                              │  - 商品子任务: 50台空调              │
                              │  - 服务子任务: 含安装                 │
                              │  - target_unit_price: 加权平均预算    │
                              │  - buyer_task_ids: [A, B, C]        │
                              └────────────────────────────────────┘
                                                       │
                                                       ↓
                                          TenderTask.publish()
                                          事件: TASK_PUBLISHED
                                                       │
                                                       ↓
供应商X ──┐
供应商Y ──┼──→ submit_bid(tender, supplier, bid) ──→ TenderTask.proposals 累积
供应商Z ──┘
                                                       │
                                          投标截止 / 主动截标
                                                       │
                                                       ↓
                              ┌────────────────────────────────────┐
                              │ ReverseAuction.execute(tender, [])  │
                              │  - 对每个提交 bid 的 supplier 评分   │
                              │  - TenderBidScorer 计算              │
                              │  - 选最高分                          │
                              └────────────────────────────────────┘
                                                       │
                                                       ↓
                                          TenderTask.assign_to(winner)
                                          事件: TASK_ASSIGNED
                                                       │
                                                       ↓
                              ┌────────────────────────────────────┐
                              │ 创建 Deal（订单）                    │
                              │ InstallmentPayment.calculate()       │
                              │  → total_amount = 50 × 单价          │
                              │  → deposit_amount = 30%              │
                              │  → balance_amount = 70%              │
                              │ hold_deposit()  → 订金托管           │
                              └────────────────────────────────────┘
                                                       │
                                                       ↓
                                          供应商备货
                                          capture_deposit() → 扣订金
                                                       │
                                                       ↓
                              ┌────────────────────────────────────┐
                              │ 履约阶段                             │
                              │ 商品子任务: ASSIGNED→IN_PROGRESS→COMPLETED │
                              │ 服务子任务: ASSIGNED→IN_PROGRESS→COMPLETED │
                              │ 两者都 COMPLETED → TenderTask.complete() │
                              └────────────────────────────────────┘
                                                       │
                                                       ↓
                                          capture_balance() → 扣尾款
                                          Deal.complete()
                                          事件: TASK_COMPLETED
                                                       │
                                                       ↓
                              ┌────────────────────────────────────┐
                              │ 双向评价                             │
                              │ 买家×N → 评供应商 (4维)              │
                              │ 供应商 → 评买家群体 (2维)            │
                              └────────────────────────────────────┘
```

### 状态机承载

**TenderTask 状态流转（复用 Task 状态机，无新增）：**

```
DRAFT → PUBLISHED → MATCHING → ASSIGNED → IN_PROGRESS → COMPLETED
                                         ↘
                                          CANCELLED
```

- `DRAFT → PUBLISHED`：`tender.publish()` 后立即转 MATCHING
- `MATCHING`：等待供应商提交 bids（期间累积 proposals）
- `MATCHING → ASSIGNED`：`assign_to(winner)`，触发 `TASK_ASSIGNED` 事件
- `ASSIGNED → IN_PROGRESS`：`start_execution()`，供应商开始备货
- `IN_PROGRESS → COMPLETED`：两个子任务都 COMPLETED 后调用 `complete()`

**子任务状态流转（独立）：**

商品子任务和服务子任务各自走 Task 状态机，由调用方（demo/测试）显式驱动：
- `assign_to(supplier.resource_id)` → `ASSIGNED`
- `start_execution()` → `IN_PROGRESS`
- `complete()` → `COMPLETED`

### 支付状态流转

**Deal 状态机（复用，无新增）：**

```
CREATED → ACTIVE → COMPLETED
```

**PaymentOrder 状态（通过 metadata 扩展）：**

```
deposit_status: none → held → captured
balance_status: none ──────────────→ captured
order.status:    CREATED → HELD → CAPTURED
```

**关键操作时序：**
1. `InstallmentPayment.calculate()` → 生成 PaymentOrder（含 deposit_amount/balance_amount）
2. `hold_deposit()` → deposit_status=held, order.status=HELD
3. `capture_deposit()` → deposit_status=captured（订金扣款，但 order 整体仍 HELD）
4. 履约完成
5. `capture_balance()` → balance_status=captured, order.status=CAPTURED（尾款扣款，订单完结）

## 错误处理与边界情况

| 场景 | 处理方式 |
|------|---------|
| BuyerTask 数量不足阈值 | `try_aggregate()` 返回 None，不创建 TenderTask |
| 供应商未提交 bid | `ReverseAuction.execute()` 返回 `matched=False`，TenderTask 留在 MATCHING |
| 供应商无 business_license | `CredentialFilter` 过滤，不进入评分 |
| 服务能力不匹配 | `TenderBidScorer` 返回 -1.0（极低分） |
| 投标价格全部超预算 | 仍选最低价（记录现状，不强过滤——与陪驾车型不匹配的已知行为模式一致） |
| 子任务未完成就调 complete | `TenderTask.complete()` 抛 RuntimeError |
| 订金未托管就调 capture_deposit | `capture_deposit()` 抛 RuntimeError（状态前置校验） |
| 未扣订金就扣尾款 | `capture_balance()` 抛 RuntimeError（状态前置校验） |
| CompositeBidScorer 单 bid 场景 | 价格分和交期分均为 1.0（中性满分，无对比基准） |
| BrokerAgent 重复聚合 | 聚合后该批 BuyerTask 从缓冲池移除 |

## 文件结构

### 核心库修改（4 个文件，新增 2 个类 + 配套导出）
- 修改：`src/umcp_core/layers/l3/matching.py` — 新增 `CompositeBidScorer` 评分器类（追加在文件末尾）
- 修改：`src/umcp_core/layers/l3/__init__.py` — 导出 `CompositeBidScorer`
- 修改：`src/umcp_core/layers/l4/transaction.py` — 新增 `InstallmentPayment` 支付策略（追加在文件末尾）
- 修改：`src/umcp_core/layers/l4/__init__.py` — 导出 `InstallmentPayment`

### 集采插件包新增
- 创建：`plugins/group_buying/__init__.py` — `PLUGIN_MANIFEST` + `register_plugin` 钩子
- 创建：`plugins/group_buying/plugin.json` — 声明性配置
- 创建：`plugins/group_buying/tasks.py` — `BuyerTask` + `TenderTask`
- 创建：`plugins/group_buying/resources.py` — `SupplierResource`
- 创建：`plugins/group_buying/scoring.py` — `TenderBidScorer`
- 创建：`plugins/group_buying/broker.py` — `BrokerAgent`
- 创建：`plugins/group_buying/tests/__init__.py` — 空文件
- 创建：`plugins/group_buying/tests/test_tasks.py` — `BuyerTask` + `TenderTask` 测试
- 创建：`plugins/group_buying/tests/test_resources.py` — `SupplierResource` 测试
- 创建：`plugins/group_buying/tests/test_scoring.py` — `TenderBidScorer` 测试
- 创建：`plugins/group_buying/tests/test_broker.py` — `BrokerAgent` 测试
- 创建：`plugins/group_buying/tests/test_plugin_loading.py` — 插件加载机制测试

### 端到端测试与 demo
- 创建：`tests/test_composite_bid_scorer.py` — 核心库 `CompositeBidScorer` 测试
- 创建：`tests/test_installment_payment.py` — 核心库 `InstallmentPayment` 测试
- 创建：`tests/test_end_to_end_group_buying.py` — 完整交易流程测试
- 创建：`examples/group_buying_demo.py` — 可运行 demo 脚本

### 配置
- 不修改：`pyproject.toml`（`testpaths` 和 `pythonpath` 已包含 `tests` 和 `plugins`，阶段一已配置）

## 测试策略

### 核心库新增测试（`tests/`）

| 文件 | 测试数 | 覆盖内容 |
|------|--------|----------|
| `tests/test_composite_bid_scorer.py` | 7 | 价格归一化、交期归一化、信誉分、加权综合、权重边界、无 bid 数据时返回 0、高分优先方向 |
| `tests/test_installment_payment.py` | 8 | calculate 金额拆分、hold_deposit、capture_deposit、capture_balance、未托管直接 capture 抛错、未扣订金扣尾款抛错、commission 计算、deposit_ratio 边界 |

### 集采插件包测试（`plugins/group_buying/tests/`）

| 文件 | 测试数 | 覆盖内容 |
|------|--------|----------|
| `test_tasks.py` | 10 | BuyerTask 字段/默认值/预算、TenderTask 字段/子任务列表/buyer_task_ids、TenderTask.complete() 前置校验（子任务未完成抛错、全完成成功） |
| `test_resources.py` | 7 | SupplierResource 字段/默认能力 business_license/自定义 capabilities 覆盖/trust_score 默认值/service_capability 标签 |
| `test_scoring.py` | 8 | 资质硬约束返回 -1.0、服务标签不匹配返回 -1.0、全维度评分、价格越低分越高、交期越短分越高、信誉越高分越高、组合权重验证 |
| `test_broker.py` | 7 | submit_buyer_task 缓冲、try_aggregate 阈值不足返回 None、阈值达标创建 TenderTask、TenderTask 字段正确性（total_quantity/buyer_task_ids）、多品类独立聚合、重复聚合防护、notify_buyers 事件发送 |
| `test_plugin_loading.py` | 8 | 插件加载、task_factory 注册 buyer+tender 两种类型、match_strategy 为 ReverseAuction、payment_schema 为 InstallmentPayment、trust_engine 注入、access_rule 包含 business_license、信任维度 4 维、deposit_ratio=0.3 配置 |

### 端到端测试（`tests/`）

| 文件 | 测试数 | 覆盖内容 |
|------|--------|----------|
| `tests/test_end_to_end_group_buying.py` | 5 | 完整流程（聚合→招标→报价→选标→分期支付→履约→评价）、多供应商时最优报价中标、无 business_license 供应商被过滤、聚合不足时不开标、子任务未完成时 TenderTask.complete 抛错 |

### Demo 脚本（`examples/`）

| 文件 | 说明 |
|------|------|
| `examples/group_buying_demo.py` | 10 步流程：加载插件→3 买家提交需求→BrokerAgent 聚合→发起 TenderTask→3 供应商报价→系统选标→分期支付托管→履约（商品+服务子任务）→扣尾款→双向评价+事件审计 |

### 测试规模预估

| 类别 | 测试数 |
|------|--------|
| 阶段一+二基线 | 163 |
| 核心库新增 | 7 + 8 = 15 |
| 插件包新增 | 10 + 7 + 8 + 7 + 8 = 40 |
| 端到端 | 5 |
| **总计** | **223** |

## 任务分解预估（13 个任务）

| # | 任务 | 类型 |
|---|------|------|
| 1 | 核心库新增 CompositeBidScorer（TDD） | 核心库 |
| 2 | 核心库新增 InstallmentPayment（TDD） | 核心库 |
| 3 | 创建集采插件包骨架与 plugin.json | 骨架 |
| 4 | 实现 BuyerTask（TDD） | 插件 |
| 5 | 实现 TenderTask（含完成判定逻辑，TDD） | 插件 |
| 6 | 实现 SupplierResource（TDD） | 插件 |
| 7 | 实现 TenderBidScorer（TDD） | 插件 |
| 8 | 实现 BrokerAgent（TDD） | 插件 |
| 9 | 实现 PLUGIN_MANIFEST 与 register_plugin 钩子 | 插件 |
| 10 | 测试插件加载机制 | 测试 |
| 11 | 基于插件的端到端测试 | 测试 |
| 12 | 编写可运行 demo 脚本 | demo |
| 13 | 全量回归 + 文档更新 | 收尾 |

## 验证目标达成度

| 目标 | 验证方式 |
|------|---------|
| 通过"扩展预置策略"承载集采行业 | 插件包 + register_plugin 钩子注入，未碰核心抽象 |
| "未修改抽象基类" | `src/umcp_core/core/` 零改动，仅 L3/L4 层新增 2 个通用策略 |
| 与网约车/陪驾差异足够大 | C2B 反向竞价（vs C2C 实时匹配）、N-to-1 聚合（vs 1-to-1）、混合任务（vs 单一任务）、分期付款（vs 一手交钱） |
| 核心库复用度 | 复用 CustomTask.proposals + PackageTask + ReverseAuction + WeightedSumTrustEngine + CredentialFilter + FlatCommissionRule，新增 CompositeBidScorer + InstallmentPayment |
| 补齐前两阶段未验证组件 | CustomTask.proposals 机制、PackageTask 编排、ReverseAuction/Bidding 匹配策略、分期付款状态机 |
