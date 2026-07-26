# 阶段二：陪驾服务插件设计规格

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

## 目标

通过实现陪驾服务行业插件，验证 UMCP 核心抽象（三段式架构）能否通过"扩展预置策略、不修改抽象基类"的方式承载**与网约车差异足够大**的第二个行业，从而证明核心抽象的通用性。

## 架构原则

**核心库预置策略 = 跨行业通用的策略**

- 通用策略 → 核心库（如 `SkillMatchStrategy`、`HourlyPricing`，任何技能匹配或按时长计费的场景都可用）
- 行业特有逻辑 → 行业插件（如陪驾的教练等级加权、网约车的距离评分）

陪驾采用与网约车一致的**实时模式**（实时预约、实时服务、按时长计费），不引入预约制相关的时间窗口约束。

## 陪驾 vs 网约车 差异矩阵

| 维度 | 网约车（阶段一） | 陪驾（阶段二） | 通用策略 / 行业策略 |
|------|----------------|---------------|-------------------|
| 时间模式 | 实时 | 实时 | 一致，无需新策略 |
| 匹配依据 | 地理距离（近者优先） | 技能标签（车型+教练等级） | `SkillMatchStrategy`（通用） + `EscortMatchScorer`（行业） |
| 定价方式 | 距离动态定价 | 按时长计费 | `HourlyPricing`（通用） + `DynamicPricing`（行业，网约车用） |
| 信任维度 | 准时/整洁/驾驶平稳/沟通 | 教学能力/耐心/安全记录 | `WeightedSumTrustEngine`（通用） + 维度配置（行业） |
| 角色双边 | 乘客 ↔ 司机 | 学员 ↔ 教练 | 一致，复用 L1/L6/L7 |

## 核心库新增预置策略

### 1. `SkillMatchScorer`（L3 匹配层通用评分器）

**文件：** `src/umcp_core/layers/l3/matching.py`

**职责：** 基于技能标签交集数量评分的**评分器**（scorer，可调用对象），不是独立的 `MatchStrategy` 实现。学员任务声明的需求标签集合与教练资源提供的能力标签集合的交集大小作为评分。交集越大评分越高。

**为何是 scorer 而非 MatchStrategy：** 复用阶段一验证过的 `InstantMatch` 策略（负责排序、过滤、选最优），只把评分逻辑抽出来作为可注入的 scorer。这与网约车 `RideMatchScorer` 的模式一致，保持核心库内部一致性。

**通用性论证：** 任何需要技能匹配的场景（陪驾、家教、家政、维修）都可复用，不绑定陪驾语义。

**接口契约：**
- 类型：可调用类（实现 `__call__(task, resource) -> float`）
- 输入：`Task`（包含 `required_skills` 字段，类型 `list[str]`，存于 `structured_fields`）、`Resource`（包含 `skills` 字段，类型 `list[str]`，存于 `metadata`）
- 输出：`float`，交集数量（0 表示无匹配）
- 评分方向：**降序优先**（与 `InstantMatch` 的 `reverse=True` 一致，分数高者优先）

**与 InstantMatch 集成：** 作为 `scorer` 参数注入 `InstantMatch(scorer=SkillMatchScorer())`，由 `InstantMatch` 负责排序和过滤。

### 2. `HourlyPricing`（L4 支付层通用策略）

**文件：** `src/umcp_core/layers/l4/pricing.py`

**职责：** 按时长计费。`hourly_rate × duration_hours`，支持整数小时和小数小时（按分钟折算）。

**通用性论证：** 任何按时长计费的场景（陪驾、家教、咨询、租赁）都可复用。

**接口契约：**
- 输入：`Task`（包含 `duration_hours` 字段，类型 `float`）、`hourly_rate`（构造时配置）
- 输出：`float`，总价
- 课时包折扣：YAGNI，本期不实现。如有需要后续扩展。

**与交易流程集成：** 由 `register_plugin` 注入为 `payment_schema`，供 L4 支付层调用计算托管金额。

## 陪驾插件包结构

```
plugins/escort_driving/
├── __init__.py              # PLUGIN_MANIFEST + register_plugin 钩子
├── plugin.json              # 声明性配置（与 PLUGIN_MANIFEST 字段一致）
├── tasks.py                 # EscortTask：车型需求+技能标签+预期时长+集合点
├── resources.py             # CoachResource：车型+等级+技能标签+位置
├── scoring.py               # EscortMatchScorer：行业策略（技能匹配+等级加权）
└── tests/
    ├── __init__.py
    ├── test_tasks.py
    ├── test_resources.py
    ├── test_scoring.py
    └── test_plugin_loading.py
```

## 行业策略：EscortMatchScorer

**文件：** `plugins/escort_driving/scoring.py`

**职责：** 陪驾行业专有的匹配评分器，组合通用策略与行业逻辑：

1. 调用通用 `SkillMatchStrategy` 计算技能匹配分（交集数量）
2. 行业加权：
   - 车型必须匹配（硬性约束，不匹配返回 -∞ 或极低分）
   - 教练等级加权（A 级 > B 级，差值作为加分项）
3. 返回综合评分

**评分方向：** 降序优先（与 `InstantMatch` 的 `reverse=True` 一致）。

**为何不放核心库：** 教练等级加权是陪驾特有逻辑，其他行业（家教、家政）有不同的等级体系，无法通用。

## 业务流程（实时模式）

1. **教练出车**：注册 `CoachResource`，包含车型（manual/automatic）、等级（A/B）、技能标签（如 `highway`、`night`、`parking`）、当前位置
2. **学员发单**：创建 `EscortTask`，包含车型需求、技能标签需求、预期时长（小时）、集合地点
3. **系统实时匹配**：`EscortMatchScorer` 评分（技能匹配为主，等级加权为辅），`InstantMatch` 选出最高分教练
4. **服务开始** → **服务结束**：状态机驱动
5. **按时长计费**：`HourlyPricing` 计算总价（`hourly_rate × duration_hours`），20% 平台抽成
6. **双向评价**：3 维度信誉画像（教学能力/耐心/安全记录），`WeightedSumTrustEngine` 聚合

## 文件清单

### 核心库新增（2 个文件修改）
- 修改：`src/umcp_core/layers/l3/matching.py` — 新增 `SkillMatchScorer` 评分器
- 修改：`src/umcp_core/layers/l4/pricing.py` — 新增 `HourlyPricing` 类
- 修改：`src/umcp_core/layers/l3/__init__.py` — 导出 `SkillMatchScorer`
- 修改：`src/umcp_core/layers/l4/__init__.py` — 导出 `HourlyPricing`

### 陪驾插件包新增
- 创建：`plugins/escort_driving/__init__.py`
- 创建：`plugins/escort_driving/plugin.json`
- 创建：`plugins/escort_driving/tasks.py`
- 创建：`plugins/escort_driving/resources.py`
- 创建：`plugins/escort_driving/scoring.py`
- 创建：`plugins/escort_driving/tests/__init__.py`
- 创建：`plugins/escort_driving/tests/test_tasks.py`
- 创建：`plugins/escort_driving/tests/test_resources.py`
- 创建：`plugins/escort_driving/tests/test_scoring.py`
- 创建：`plugins/escort_driving/tests/test_plugin_loading.py`

### 端到端测试与 demo
- 创建：`tests/test_end_to_end_escort.py`
- 创建：`examples/escort_driving_demo.py`

### 配置
- 修改：`pyproject.toml` — 在 `testpaths` 和 `pythonpath` 中已包含 `tests` 和 `plugins`，无需修改

## 验证成功标准

- [ ] 核心库新增 2 个通用预置策略（`SkillMatchStrategy`、`HourlyPricing`）
- [ ] 陪驾插件包完整实现（5 个核心文件 + 5 个测试文件）
- [ ] 阶段一网约车 121 测试无回归
- [ ] 陪驾插件新增测试 ≥ 30 个
- [ ] 端到端测试跑通完整实时交易流程
- [ ] demo 脚本可独立运行
- [ ] 跨插件契约验证：`PLUGIN_MANIFEST` 与 `plugin.json` 字段一致

## 非目标（YAGNI）

- **不实现** 预约制时间窗口约束（陪驾采用实时模式）
- **不实现** 课时包折扣（`HourlyPricing` 仅基础计费）
- **不实现** 教练排班/可用时段管理（实时模式无需）
- **不修改** 核心库抽象基类（`Task`、`Resource`、`MatchStrategy` 等）
- **不重构** 阶段一网约车插件代码（除非发现回归 bug）

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| `SkillMatchScorer` 评分方向与 `InstantMatch` 不匹配 | 复用阶段一 `RideMatchScorer` 的评分模式：返回正分（交集数量），配合 `InstantMatch` 的 `reverse=True` |
| 通用策略过度抽象 | 严格遵循 YAGNI，只实现陪驾场景需要的功能，不预设未来扩展 |
| 陪驾插件与网约车插件命名冲突 | 插件包独立目录 `plugins/escort_driving/`，`task_type` 用 `"escort"` 避免冲突 |
| 核心库修改破坏阶段一测试 | 每次核心库修改后立即运行全部测试（121 + 新增） |

## 后续演进路径

阶段二完成后：
1. **合并分支** 到 main 固化多行业基线
2. **对比测试套件**（可选）：编写网约车 vs 陪驾的对比测试，明确验证同一核心库同时承载两种场景
3. **阶段三**：进入生产化演进（Postgres 仓储层、并发控制等）
