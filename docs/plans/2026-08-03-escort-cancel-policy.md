# 陪驾业务切片3：取消策略 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现陪驾订单的取消策略闭环——实时单超时自动取消 + 超时扩展搜索范围 + 用户手动取消（预约单按时间梯度扣信用值），由规则配置中心驱动，前端倒计时与取消确认 UI 联动。

**架构：**
- 后端：修复 `Task.cancel()` 事件 bug（发 `TASK_CANCELLED` 而非 `TASK_COMPLETED`）；扩展 `TrustEngine.apply_penalty()` 扣信用分；在陪驾插件注册 `RuleConfig` 并预加载默认规则；新增轻量 asyncio `SchedulerService` 在 FastAPI lifespan 中运行，每秒扫描待取消的实时单；重写 `cancel_order` 端点按规则扣除信用值。
- 前端：倒计时组件（基于 `timeout_seconds` 规则）、取消确认对话框（预约单显示罚分提示）、WS 事件 `task.cancelled` 联动列表与详情页。

**技术栈：** FastAPI + Pydantic + asyncio（调度器）、Zustand + React Query + shadcn/ui（前端）、pytest + Vitest（测试）。

---

## 关键设计决策

### 取消策略矩阵

| 场景 | 触发方 | 行为 | 罚分 |
|------|--------|------|------|
| 实时单超时（无教练抢单） | 系统（SchedulerService） | 自动 `task.cancel()`，WS 推送 `task.cancelled` 给学员 | 无 |
| 实时单超时扩展搜索 | 系统（SchedulerService） | 再次广播抢单邀请给在线教练（标记 `expanded: true`） | 无 |
| 实时单用户手动取消 | 学员 | `task.cancel()`，WS 推送 `task.cancelled` 给已抢单教练（若有） | 无 |
| 预约单用户手动取消 | 学员 | `task.cancel()` + `deal.cancel()` + 退款 + 按时间梯度扣信用分 | 按梯度 |
| 预约单教练拒绝 | 教练 | 切片2已实现（自动退款，不扣学员信用） | 无 |

### 预约单取消罚分梯度（默认值，可由规则配置覆盖）

```json
[
  {"hours_before": 24, "penalty": 0.2},
  {"hours_before": 12, "penalty": 0.5},
  {"hours_before": 4,  "penalty": 1.0},
  {"hours_before": 0,  "penalty": 2.0}
]
```

语义：取消时距预约时间 `scheduled_at` 的小时差 `h`，匹配第一个 `h >= hours_before` 的档位扣 `penalty` 分。越临近扣越多。

### 规则配置 Key

| Key | 默认值 | 说明 |
|-----|--------|------|
| `escort.cancel.realtime.timeout_seconds` | `60` | 实时单下单后多少秒无教练抢单则自动取消 |
| `escort.cancel.realtime.expand_after_seconds` | `30` | 实时单下单后多少秒无教练抢单则扩展搜索范围（再次广播） |
| `escort.cancel.scheduled.penalty_tiers` | 见上 | 预约单取消罚分梯度 |

### Task.cancel() Bug 修复说明

当前 `Task.cancel()` 发布的是 `TASK_COMPLETED` 事件（payload `{"cancelled": True}`），与 `WS_PUSHABLE_EVENTS` 中的 `TASK_CANCELLED` 不匹配，导致取消后前端无法通过 WS 收到推送。本切片任务1修复此 bug。

---

## 文件结构

### 后端

- **修改** `src/umcp_core/core/task.py`：修复 `cancel()` 事件类型为 `TASK_CANCELLED`。
- **修改** `src/umcp_core/layers/l5/trust.py`：`WeightedSumTrustEngine` 新增 `apply_penalty(user_id, points, reason)` 方法。
- **修改** `plugins/escort_driving/__init__.py`：在 `register_plugin` 中创建 `RuleConfig`，预加载默认规则，挂载到 `server.rule_config`。
- **创建** `src/umcp_core/transport/scheduler.py`：轻量 asyncio 调度器 `SchedulerService`，注册 worker 并周期执行。
- **创建** `src/umcp_core/transport/workers/__init__.py`：workers 包初始化。
- **创建** `src/umcp_core/transport/workers/realtime_cancel_worker.py`：实时单超时自动取消 + 扩展搜索范围 worker。
- **修改** `src/umcp_core/transport/app.py`：在 lifespan 中启动 `SchedulerService`，shutdown 时停止。
- **修改** `src/umcp_core/transport/routers/escort/orders.py`：重写 `cancel_order` 端点，按规则扣除信用分；扩展 `OrderInfo` 增加 `cancel_penalty` 字段。
- **修改** `plugins/escort_driving/__init__.py`：注册 `RealtimeCancelWorker` 到 `SchedulerService`（通过 server 引用，在 app 启动时装配）。
- **测试** `tests/test_task_cancel_event.py`：验证 cancel 发 `TASK_CANCELLED` 事件。
- **测试** `tests/test_trust_penalty.py`：验证 `apply_penalty` 扣分。
- **测试** `tests/test_rule_config_defaults.py`：验证默认规则加载。
- **测试** `tests/test_scheduler_service.py`：验证调度器启停与 worker 注册。
- **测试** `tests/test_realtime_cancel_worker.py`：验证超时取消与扩展搜索。
- **测试** `tests/test_escort_cancel_policy.py`：验证取消端点按梯度扣分。

### 前端

- **修改** `web/src/types/escort.ts`：扩展 `OrderInfo` 增加 `cancel_penalty` 字段；新增 `CancelRules` 接口。
- **创建** `web/src/hooks/use-cancel-rules.ts`：获取取消规则（供倒计时与罚分提示使用）。
- **创建** `web/src/components/countdown-timer.tsx`：实时单倒计时组件。
- **创建** `web/src/components/cancel-dialog.tsx`：取消确认对话框（预约单显示罚分提示）。
- **修改** `web/src/app/(protected)/escort/student/orders/[id]/page.tsx`：集成倒计时与取消对话框。
- **修改** `web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`：监听 `task.cancelled` 事件刷新。
- **测试** `web/tests/cancel-policy.test.ts`：测试 hooks 与组件逻辑。

---

## 任务分解

### 任务 1：修复 Task.cancel() 事件类型 bug

**文件：**
- 修改：`src/umcp_core/core/task.py:98-103`
- 测试：`tests/test_task_cancel_event.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_task_cancel_event.py`：

```python
"""验证 Task.cancel() 发布 TASK_CANCELLED 事件（而非 TASK_COMPLETED）。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import Task, TaskStatus
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType


class _TestTask(Task):
    def task_type(self) -> str:
        return "test"


def _collect_events(bus: EventBus) -> list:
    events: list = []
    bus.subscribe_all(lambda e: events.append(e))
    return events


def test_cancel_emits_task_cancelled_event():
    """cancel() 应发布 TASK_CANCELLED 事件。"""
    bus = EventBus()
    events = _collect_events(bus)

    task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
    task.bind_event_bus(bus)
    task.publish_for_claim()
    events.clear()

    task.cancel()

    assert task.status == TaskStatus.CANCELLED
    assert any(e.type == EventType.TASK_CANCELLED for e in events), \
        "cancel() 应发布 TASK_CANCELLED 事件"
    assert not any(e.type == EventType.TASK_COMPLETED for e in events), \
        "cancel() 不应发布 TASK_COMPLETED 事件"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_task_cancel_event.py -v`
预期：FAIL，断言失败 "cancel() 应发布 TASK_CANCELLED 事件"。

- [ ] **步骤 3：修复实现**

修改 `src/umcp_core/core/task.py` 的 `cancel` 方法（第 98-103 行）：

```python
    def cancel(self) -> None:
        """取消任务。"""
        if TaskStatus.is_terminal(self.status):
            raise RuntimeError(f"任务已处于终态 {self.status}，无法取消")
        self._transition(TaskStatus.CANCELLED)
        self._emit(EventType.TASK_CANCELLED, payload={"cancelled": True})
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_task_cancel_event.py -v`
预期：PASS

- [ ] **步骤 5：回归现有测试**

运行：`pytest tests/test_core.py -v`
预期：PASS（现有测试只检查状态，不检查事件类型，不受影响）。

- [ ] **步骤 6：Commit**

```bash
git add tests/test_task_cancel_event.py src/umcp_core/core/task.py
git commit -m "fix(core): Task.cancel() 发布 TASK_CANCELLED 事件而非 TASK_COMPLETED"
```

---

### 任务 2：扩展 TrustEngine.apply_penalty

**文件：**
- 修改：`src/umcp_core/layers/l5/trust.py:78-122`
- 测试：`tests/test_trust_penalty.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_trust_penalty.py`：

```python
"""验证 TrustEngine.apply_penalty 扣分逻辑。"""
from __future__ import annotations

from umcp_core.layers.l5.trust import WeightedSumTrustEngine


def test_apply_penalty_reduces_overall_score():
    """扣分应降低 overall_score，不低于 0。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    # 先记录一个正向评分，使 overall_score > 0
    from umcp_core.layers.l5.trust import Evaluation
    engine.record_evaluation(Evaluation(
        evaluation_id="e1",
        evaluator_id="coach1",
        evaluatee_id="student1",
        ratings={"overall": 4.0},
        comment="",
    ))
    profile = engine.evaluate("student1")
    assert profile.overall_score == 4.0

    # 扣 1.5 分
    engine.apply_penalty("student1", 1.5, reason="预约单临时取消")
    profile = engine.evaluate("student1")
    assert profile.overall_score == 2.5

    # 再扣 5 分，应降到 0（不低于 0）
    engine.apply_penalty("student1", 5.0, reason="再次取消")
    profile = engine.evaluate("student1")
    assert profile.overall_score == 0.0


def test_apply_penalty_unknown_user_starts_from_zero():
    """未评价过的用户从 0 分起扣，仍为 0。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    engine.apply_penalty("unknown_user", 2.0, reason="测试")
    profile = engine.evaluate("unknown_user")
    assert profile.overall_score == 0.0


def test_apply_penalty_negative_points_ignored():
    """负分应被忽略（不允许通过 apply_penalty 加分）。"""
    engine = WeightedSumTrustEngine(dimensions=["overall"])
    engine.apply_penalty("u1", -1.0, reason="非法")
    profile = engine.evaluate("u1")
    assert profile.overall_score == 0.0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_trust_penalty.py -v`
预期：FAIL，`AttributeError: 'WeightedSumTrustEngine' object has no attribute 'apply_penalty'`。

- [ ] **步骤 3：实现 apply_penalty**

修改 `src/umcp_core/layers/l5/trust.py`，在 `TrustEngine` 抽象基类（第 78-91 行附近）添加抽象方法，在 `WeightedSumTrustEngine`（第 93-122 行附近）添加实现。

在 `TrustEngine` 类的 `record_evaluation` 抽象方法之后添加：

```python
    @abstractmethod
    def apply_penalty(self, user_id: str, points: float, reason: str) -> TrustProfile:
        """对用户扣分（不影响维度分，只降 overall_score，不低于 0）。

        Args:
            user_id: 被扣分用户
            points: 扣分分值（负数视为 0，不加分）
            reason: 扣分原因（记录用，未来可扩展审计）

        Returns:
            扣分后的最新 TrustProfile
        """
```

在 `WeightedSumTrustEngine.record_evaluation` 方法之后添加：

```python
    def apply_penalty(self, user_id: str, points: float, reason: str) -> TrustProfile:
        """直接从 overall_score 扣分（不低于 0）。

        实现策略：把 overall_score 视为独立标量，扣分后单独写回。
        维度分不变（维度分反映历史评价，扣分是行为惩罚，不应抹除评价记录）。
        为此在 TrustProfile 上引入 _penalty_offset 累计扣分，overall_score 计算时减去。
        """
        if points <= 0:
            return self.evaluate(user_id)
        profile = self.evaluate(user_id)
        offset = getattr(profile, "_penalty_offset", 0.0) + points
        # 通过对象动态属性累计 offset（TrustProfile 是 dataclass，允许 setattr）
        object.__setattr__(profile, "_penalty_offset", offset)
        # 重新计算 overall_score = max(0, 原始均分 - offset)
        raw = (
            sum(profile.dimension_scores.values()) / len(profile.dimension_scores)
            if profile.dimension_scores else 0.0
        )
        profile.overall_score = max(0.0, raw - offset)
        return profile
```

注意：`TrustProfile` 是 `@dataclass`，`overall_score` 是普通字段可直接赋值。`_penalty_offset` 通过 `object.__setattr__` 设置避免 dataclass frozen 限制（当前未 frozen，直接 `setattr` 也可，但用 `object.__setattr__` 更安全）。

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_trust_penalty.py -v`
预期：PASS

- [ ] **步骤 5：回归测试**

运行：`pytest tests/ -k "trust" -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add tests/test_trust_penalty.py src/umcp_core/layers/l5/trust.py
git commit -m "feat(trust): TrustEngine 新增 apply_penalty 支持信用分扣除"
```

---

### 任务 3：注册 RuleConfig 到 server 并预加载默认规则

**文件：**
- 修改：`plugins/escort_driving/__init__.py`
- 测试：`tests/test_rule_config_defaults.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_rule_config_defaults.py`：

```python
"""验证陪驾插件注册 RuleConfig 并预加载默认取消规则。"""
from __future__ import annotations

import pytest

from umcp_core.server import UMCPServer
from umcp_core.shared.rules.config import RuleConfig
from umcp_core.shared.rules.repository import InMemoryRuleRepository


@pytest.fixture
def server_with_escort() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    # 加载陪驾插件（路径与 conftest.py 中 sys.path 配置一致）
    server.load_plugin("escort_driving")
    return server


def test_rule_config_registered(server_with_escort: UMCPServer):
    """server.rule_config 应为 RuleConfig 实例。"""
    assert hasattr(server_with_escort, "rule_config")
    assert isinstance(server_with_escort.rule_config, RuleConfig)


def test_default_realtime_timeout_seconds(server_with_escort: UMCPServer):
    """默认实时单超时 60 秒。"""
    value = server_with_escort.rule_config.get("escort.cancel.realtime.timeout_seconds")
    assert value == 60


def test_default_realtime_expand_after_seconds(server_with_escort: UMCPServer):
    """默认实时单扩展搜索 30 秒。"""
    value = server_with_escort.rule_config.get("escort.cancel.realtime.expand_after_seconds")
    assert value == 30


def test_default_scheduled_penalty_tiers(server_with_escort: UMCPServer):
    """默认预约单罚分梯度。"""
    tiers = server_with_escort.rule_config.get("escort.cancel.scheduled.penalty_tiers")
    assert tiers == [
        {"hours_before": 24, "penalty": 0.2},
        {"hours_before": 12, "penalty": 0.5},
        {"hours_before": 4, "penalty": 1.0},
        {"hours_before": 0, "penalty": 2.0},
    ]


def test_rule_config_set_overrides_default(server_with_escort: UMCPServer):
    """set 后应覆盖默认值并刷新缓存。"""
    server_with_escort.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=120,
        updated_by="admin",
        category="escort.cancel",
        reason="运营调整",
    )
    assert server_with_escort.rule_config.get("escort.cancel.realtime.timeout_seconds") == 120
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_rule_config_defaults.py -v`
预期：FAIL，`AttributeError: 'UMCPServer' object has no attribute 'rule_config'`。

- [ ] **步骤 3：在 register_plugin 中注册 RuleConfig**

修改 `plugins/escort_driving/__init__.py`，在 `register_plugin` 函数末尾（`server.payment_service = ...` 之后）添加：

```python
    # 注册规则配置中心（内存仓储 + 默认值预加载，挂载到 server.rule_config）
    from umcp_core.shared.rules.config import RuleConfig
    from umcp_core.shared.rules.repository import InMemoryRuleRepository

    rule_config = RuleConfig(repo=InMemoryRuleRepository())
    rule_config.set_defaults(
        {
            "escort.cancel.realtime.timeout_seconds": 60,
            "escort.cancel.realtime.expand_after_seconds": 30,
            "escort.cancel.scheduled.penalty_tiers": [
                {"hours_before": 24, "penalty": 0.2},
                {"hours_before": 12, "penalty": 0.5},
                {"hours_before": 4, "penalty": 1.0},
                {"hours_before": 0, "penalty": 2.0},
            ],
        }
    )
    server.rule_config = rule_config
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_rule_config_defaults.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add tests/test_rule_config_defaults.py plugins/escort_driving/__init__.py
git commit -m "feat(escort): 注册 RuleConfig 并预加载取消策略默认规则"
```

---

### 任务 4：实现 SchedulerService 调度器框架

**文件：**
- 创建：`src/umcp_core/transport/scheduler.py`
- 测试：`tests/test_scheduler_service.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_scheduler_service.py`：

```python
"""验证 SchedulerService 调度器框架。"""
from __future__ import annotations

import asyncio

import pytest

from umcp_core.transport.scheduler import SchedulerService


class _CountingWorker:
    """计数 worker，记录被调用次数。"""

    def __init__(self, name: str = "counter"):
        self.name = name
        self.call_count = 0
        self.last_context = None

    async def run(self, context) -> None:
        self.call_count += 1
        self.last_context = context


@pytest.mark.asyncio
async def test_scheduler_runs_workers_periodically():
    """调度器应按间隔周期调用 worker。"""
    scheduler = SchedulerService(interval_seconds=0.05)
    worker = _CountingWorker()
    scheduler.register(worker)

    task = asyncio.create_task(scheduler.start(context={"server": "fake"}))
    await asyncio.sleep(0.18)  # 约 3-4 个周期
    await scheduler.stop()
    await task

    assert worker.call_count >= 3, f"应至少调用 3 次，实际 {worker.call_count}"
    assert worker.last_context == {"server": "fake"}


@pytest.mark.asyncio
async def test_scheduler_stop_is_idempotent():
    """stop 应可重复调用。"""
    scheduler = SchedulerService(interval_seconds=0.1)
    worker = _CountingWorker()
    scheduler.register(worker)

    task = asyncio.create_task(scheduler.start(context=None))
    await asyncio.sleep(0.05)
    await scheduler.stop()
    await scheduler.stop()  # 不应抛异常
    await task


@pytest.mark.asyncio
async def test_scheduler_worker_exception_does_not_crash_loop():
    """单个 worker 抛异常不应影响其他 worker 与后续周期。"""
    class _BoomWorker:
        name = "boom"

        async def run(self, context) -> None:
            raise RuntimeError("boom")

    scheduler = SchedulerService(interval_seconds=0.05)
    boom = _BoomWorker()
    counter = _CountingWorker()
    scheduler.register(boom)
    scheduler.register(counter)

    task = asyncio.create_task(scheduler.start(context=None))
    await asyncio.sleep(0.15)
    await scheduler.stop()
    await task

    assert counter.call_count >= 2, "异常 worker 不应阻断其他 worker"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_scheduler_service.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.transport.scheduler'`。

- [ ] **步骤 3：实现 SchedulerService**

创建 `src/umcp_core/transport/scheduler.py`：

```python
"""轻量 asyncio 调度器服务。

在 FastAPI lifespan 中启动，周期性执行注册的 worker（如取消策略 worker）。
worker 需实现 `async def run(self, context) -> None` 接口。
单个 worker 抛异常会被捕获并记录，不影响其他 worker 或后续周期。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Worker(Protocol):
    """调度器 worker 协议。"""

    name: str

    async def run(self, context: Any) -> None:
        """执行一次周期任务。context 由 SchedulerService.start 传入。"""
        ...


class SchedulerService:
    """周期性调度器。

    Args:
        interval_seconds: 调度间隔（秒），默认 1.0。
    """

    def __init__(self, interval_seconds: float = 1.0) -> None:
        self._interval = interval_seconds
        self._workers: list[Worker] = []
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    def register(self, worker: Worker) -> None:
        """注册 worker。"""
        self._workers.append(worker)

    async def start(self, context: Any = None) -> None:
        """启动调度循环（阻塞直至 stop 被调用）。"""
        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            for worker in self._workers:
                try:
                    await worker.run(context)
                except Exception:
                    logger.exception(
                        "worker %s 执行异常", getattr(worker, "name", worker)
                    )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass  # 超时即进入下一周期

    async def stop(self) -> None:
        """停止调度循环。幂等。"""
        if self._stop_event is not None:
            self._stop_event.set()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_scheduler_service.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add tests/test_scheduler_service.py src/umcp_core/transport/scheduler.py
git commit -m "feat(transport): 新增 SchedulerService 轻量 asyncio 调度器"
```

---

### 任务 5：实现 RealtimeCancelWorker（超时取消 + 扩展搜索）

**文件：**
- 创建：`src/umcp_core/transport/workers/__init__.py`
- 创建：`src/umcp_core/transport/workers/realtime_cancel_worker.py`
- 测试：`tests/test_realtime_cancel_worker.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_realtime_cancel_worker.py`：

```python
"""验证 RealtimeCancelWorker 超时取消与扩展搜索逻辑。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from umcp_core.core.domain import DomainTag
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType
from umcp_core.repositories.in_memory import InMemoryTaskRepository
from umcp_core.server import UMCPServer
from umcp_core.transport.workers.realtime_cancel_worker import RealtimeCancelWorker


def _make_realtime_task(
    created_seconds_ago: int,
    domain: str = "escort",
    task_id: str | None = None,
) -> "EscortTask":  # noqa: F821
    from plugins.escort_driving.tasks import EscortTask

    task = EscortTask(
        demander_id="student1",
        domain_tag=DomainTag.of(domain),
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="REALTIME",
    )
    if task_id:
        task.task_id = task_id
    # 回退 created_at 模拟下单时间
    task.created_at = datetime.utcnow() - timedelta(seconds=created_seconds_ago)
    # 实时单处于 published 状态等待抢单
    task.bind_event_bus(EventBus())
    task.publish_for_claim()
    return task


def _make_server_with_rules(timeout: int = 60, expand_after: int = 30) -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    server.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=timeout,
        updated_by="test",
        category="escort.cancel",
    )
    server.rule_config.set(
        key="escort.cancel.realtime.expand_after_seconds",
        value=expand_after,
        updated_by="test",
        category="escort.cancel",
    )
    return server


class _FakeWsManager:
    """记录广播消息的假 ws_manager。"""

    def __init__(self) -> None:
        self.broadcasts: list[dict] = []

    async def broadcast_to_online_coaches(self, message: dict) -> None:
        self.broadcasts.append(message)


@pytest.mark.asyncio
async def test_realtime_task_auto_cancelled_after_timeout():
    """超过 timeout_seconds 的实时单应被自动取消。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    # 下单 70 秒前，超过 60 秒超时
    task = _make_realtime_task(created_seconds_ago=70)
    server.task_repo.save(task)

    events: list = []
    server.event_bus.subscribe_all(lambda e: events.append(e))

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "cancelled"
    assert any(e.type == EventType.TASK_CANCELLED for e in events)


@pytest.mark.asyncio
async def test_realtime_task_not_cancelled_before_timeout():
    """未超时的实时单不应被取消。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    task = _make_realtime_task(created_seconds_ago=20)
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "published"


@pytest.mark.asyncio
async def test_realtime_task_expanded_search_after_expand_after():
    """超过 expand_after_seconds 未抢单应再次广播扩展邀请。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    fake_ws = _FakeWsManager()
    server.ws_manager = fake_ws
    # 下单 35 秒前，超过 30 秒扩展阈值，但未超过 60 秒超时
    task = _make_realtime_task(created_seconds_ago=35)
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    # 未被取消
    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "published"
    # 至少广播过一次扩展邀请
    expanded = [m for m in fake_ws.broadcasts if m.get("data", {}).get("expanded") is True]
    assert len(expanded) >= 1, "应广播扩展搜索邀请"


@pytest.mark.asyncio
async def test_expand_search_only_once_per_task():
    """扩展搜索只广播一次（避免每个周期重复广播）。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    fake_ws = _FakeWsManager()
    server.ws_manager = fake_ws
    task = _make_realtime_task(created_seconds_ago=35)
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})
    await worker.run(context={"server": server})  # 第二个周期
    await worker.run(context={"server": server})  # 第三个周期

    expanded = [m for m in fake_ws.broadcasts if m.get("data", {}).get("expanded") is True]
    assert len(expanded) == 1, "扩展搜索只应广播一次"


@pytest.mark.asyncio
async def test_scheduled_task_not_affected_by_realtime_worker():
    """预约单不应被实时单取消 worker 影响。"""
    server = _make_server_with_rules(timeout=60, expand_after=30)
    from plugins.escort_driving.tasks import EscortTask

    task = EscortTask(
        demander_id="student1",
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="SCHEDULED",
        scheduled_at=datetime.utcnow() + timedelta(hours=2),
    )
    task.created_at = datetime.utcnow() - timedelta(seconds=70)
    server.task_repo.save(task)

    worker = RealtimeCancelWorker()
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task.task_id)
    assert refreshed.status == "draft"  # 预约单保持 draft 状态
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_realtime_cancel_worker.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.transport.workers'`。

- [ ] **步骤 3：创建 workers 包**

创建 `src/umcp_core/transport/workers/__init__.py`：

```python
"""调度器 workers 包。"""
```

- [ ] **步骤 4：实现 RealtimeCancelWorker**

创建 `src/umcp_core/transport/workers/realtime_cancel_worker.py`：

```python
"""实时单超时取消 + 扩展搜索范围 worker。

每个调度周期扫描所有 domain_tag=escort 且 status=published 的实时单：
- 若下单时间超过 `expand_after_seconds` 且未扩展过 → 再次广播抢单邀请（标记 expanded）
- 若下单时间超过 `timeout_seconds` → 自动 task.cancel()，发布 TASK_CANCELLED 事件
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from umcp_core.core.task import TaskStatus

logger = logging.getLogger(__name__)


class RealtimeCancelWorker:
    """实时单超时取消 worker。"""

    name = "realtime_cancel"

    def __init__(self) -> None:
        # 记录已扩展过的 task_id，避免重复广播
        self._expanded_task_ids: set[str] = set()

    async def run(self, context: Any) -> None:
        server = context.get("server") if context else None
        if server is None:
            return

        rule_config = getattr(server, "rule_config", None)
        if rule_config is None:
            return

        timeout_seconds = rule_config.get(
            "escort.cancel.realtime.timeout_seconds", default=60
        )
        expand_after_seconds = rule_config.get(
            "escort.cancel.realtime.expand_after_seconds", default=30
        )

        now = datetime.utcnow()
        task_repo = server.task_repo
        if task_repo is None:
            return

        # 扫描所有 published 状态的 task（实时单在 published 等待抢单）
        published_tasks = task_repo.find_by_status(TaskStatus.PUBLISHED)
        for task in published_tasks:
            # 只处理陪驾 domain 的实时单
            if task.domain_tag.value != "escort":
                continue
            order_type = getattr(task, "order_type", None) or task.structured_fields.get("order_type")
            if order_type != "REALTIME":
                continue

            elapsed = (now - task.created_at).total_seconds()

            # 超时取消
            if elapsed >= timeout_seconds:
                try:
                    task.bind_event_bus(server.event_bus)
                    task.cancel()
                    task_repo.save(task)
                    logger.info("实时单 %s 超时自动取消（elapsed=%.1fs）", task.task_id, elapsed)
                except Exception:
                    logger.exception("取消实时单 %s 失败", task.task_id)
                # 已取消的从扩展集合中清理
                self._expanded_task_ids.discard(task.task_id)
                continue

            # 扩展搜索范围（未超时但超过 expand_after）
            if elapsed >= expand_after_seconds and task.task_id not in self._expanded_task_ids:
                manager = getattr(server, "ws_manager", None)
                if manager is not None:
                    message = {
                        "type": "task.published",
                        "timestamp": datetime.utcnow().isoformat(),
                        "data": {
                            "task_id": task.task_id,
                            "demander_id": task.demander_id,
                            "expanded": True,
                            "origin_lat": task.structured_fields.get("origin_lat"),
                            "origin_lng": task.structured_fields.get("origin_lng"),
                            "car_type": task.structured_fields.get("car_type"),
                            "duration_hours": task.structured_fields.get("duration_hours"),
                            "coach_level_pref": task.structured_fields.get("coach_level_pref"),
                        },
                    }
                    try:
                        await manager.broadcast_to_online_coaches(message)
                        self._expanded_task_ids.add(task.task_id)
                        logger.info("实时单 %s 扩展搜索范围（elapsed=%.1fs）", task.task_id, elapsed)
                    except Exception:
                        logger.exception("扩展搜索广播失败 task_id=%s", task.task_id)
```

- [ ] **步骤 5：运行测试验证通过**

运行：`pytest tests/test_realtime_cancel_worker.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add tests/test_realtime_cancel_worker.py src/umcp_core/transport/workers/__init__.py src/umcp_core/transport/workers/realtime_cancel_worker.py
git commit -m "feat(escort): RealtimeCancelWorker 实现超时取消与扩展搜索"
```

---

### 任务 6：在 FastAPI lifespan 中启动 SchedulerService

**文件：**
- 修改：`src/umcp_core/transport/app.py:56-72`
- 测试：`tests/test_app_scheduler_integration.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_app_scheduler_integration.py`：

```python
"""验证 FastAPI lifespan 启动 SchedulerService 并注册 RealtimeCancelWorker。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.scheduler import SchedulerService


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, app


def test_scheduler_service_attached_to_app_state(app_client):
    """app.state.scheduler 应为 SchedulerService 实例。"""
    _, app = app_client
    assert hasattr(app.state, "scheduler")
    assert isinstance(app.state.scheduler, SchedulerService)


def test_realtime_cancel_worker_registered(app_client):
    """SchedulerService 应注册 RealtimeCancelWorker。"""
    _, app = app_client
    worker_names = [w.name for w in app.state.scheduler._workers]
    assert "realtime_cancel" in worker_names
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_app_scheduler_integration.py -v`
预期：FAIL，`AttributeError: object has no attribute 'scheduler'`。

- [ ] **步骤 3：修改 app.py 集成调度器**

修改 `src/umcp_core/transport/app.py`，在文件顶部导入区添加：

```python
from umcp_core.transport.scheduler import SchedulerService
from umcp_core.transport.workers.realtime_cancel_worker import RealtimeCancelWorker
```

修改 `create_app` 函数中的 `lifespan`（第 56-72 行），在 `ws_bridge_ref["bridge"] = bridge` 之后、`yield` 之前启动调度器；在 `yield` 之后、`server.stop()` 之前停止调度器：

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        loop = asyncio.get_event_loop()
        ws_bridge_ref["loop"] = loop
        bridge = make_ws_event_bridge(ws_manager, loop)
        ws_bridge_ref["bridge"] = bridge
        server.event_bus.subscribe_all(bridge)
        # 启动调度器服务（注册 RealtimeCancelWorker）
        scheduler = SchedulerService(interval_seconds=1.0)
        scheduler.register(RealtimeCancelWorker())
        app.state.scheduler = scheduler
        scheduler_task = asyncio.create_task(scheduler.start(context={"server": server}))
        app.state.scheduler_task = scheduler_task
        logger.info("UMCP HTTP 服务已启动")
        yield
        # shutdown
        await scheduler.stop()
        try:
            await asyncio.wait_for(scheduler_task, timeout=5.0)
        except asyncio.TimeoutError:
            scheduler_task.cancel()
        if ws_bridge_ref["bridge"]:
            server.event_bus.unsubscribe_all(ws_bridge_ref["bridge"])
        await ws_manager.disconnect_all()
        server.stop()
        server.dispose()
        logger.info("UMCP HTTP 服务已停止")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_app_scheduler_integration.py -v`
预期：PASS

- [ ] **步骤 5：回归测试**

运行：`pytest tests/test_app.py -v 2>&1 | head -40`（若存在 test_app.py）；否则运行 `pytest tests/ -k "app or transport" -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add tests/test_app_scheduler_integration.py src/umcp_core/transport/app.py
git commit -m "feat(transport): FastAPI lifespan 集成 SchedulerService 与 RealtimeCancelWorker"
```

---

### 任务 7：重写 cancel_order 端点（规则驱动 + 信用值扣除）

**文件：**
- 修改：`src/umcp_core/transport/routers/escort/orders.py:206-221`
- 测试：`tests/test_escort_cancel_policy.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_escort_cancel_policy.py`：

```python
"""验证 cancel_order 端点按规则扣信用分。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _login(client, server, user_id: str = "student1") -> str:
    """注册并登录获取 token。"""
    # 直接通过 JwtService 生成 token（绕过注册流程）
    from umcp_core.core.base import User
    from umcp_core.core.domain import DomainTag
    from umcp_core.transport.auth import JwtService, make_claims

    jwt_service = JwtService(secret="test-secret")
    user = User(
        user_id=user_id,
        name=user_id,
        domain_tags=[DomainTag.of("escort")],
        roles=["demander"],
    )
    claims = make_claims(user)
    token = jwt_service.encode(claims)
    return token


def _create_realtime_task(server, user_id="student1", task_id=None):
    from datetime import datetime
    from plugins.escort_driving.tasks import EscortTask
    from umcp_core.core.domain import DomainTag

    task = EscortTask(
        demander_id=user_id,
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="REALTIME",
    )
    task.bind_event_bus(server.event_bus)
    task.publish_for_claim()
    server.task_repo.save(task)
    return task


def _create_scheduled_task(server, user_id="student1", scheduled_at=None):
    from plugins.escort_driving.tasks import EscortTask
    from umcp_core.core.domain import DomainTag

    task = EscortTask(
        demander_id=user_id,
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9,
        origin_lng=116.4,
        car_type="auto",
        required_skills=[],
        duration_hours=1,
        order_type="SCHEDULED",
        scheduled_at=scheduled_at or (datetime.utcnow() + timedelta(hours=2)),
    )
    server.task_repo.save(task)
    return task


def test_cancel_realtime_no_penalty(app_client):
    """实时单手动取消不扣信用分。"""
    client, server = app_client
    task = _create_realtime_task(server)
    token = _login(client, server)

    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "cancelled"
    assert body["data"]["cancel_penalty"] == 0.0

    # 信用分应为 0（未扣分）
    engine = server.trust_engine_for("escort")
    profile = engine.evaluate(task.demander_id)
    assert profile.overall_score == 0.0


def test_cancel_scheduled_far_in_advance_low_penalty(app_client):
    """预约单提前 25 小时取消，扣 0.2 分（命中 hours_before=24 档）。"""
    client, server = app_client
    scheduled_at = datetime.utcnow() + timedelta(hours=25)
    task = _create_scheduled_task(server, scheduled_at=scheduled_at)
    token = _login(client, server)

    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 0.2

    engine = server.trust_engine_for("escort")
    profile = engine.evaluate(task.demander_id)
    assert profile.overall_score == 0.0  # 起步 0，扣 0.2 后仍为 0（不低于 0）


def test_cancel_scheduled_close_to_time_high_penalty(app_client):
    """预约单提前 1 小时取消，扣 2.0 分（命中 hours_before=0 档）。"""
    client, server = app_client
    scheduled_at = datetime.utcnow() + timedelta(hours=1)
    task = _create_scheduled_task(server, scheduled_at=scheduled_at)
    token = _login(client, server)

    # 先给学员一个正向评分（4.0），否则扣分后仍为 0 无法验证
    from umcp_core.layers.l5.trust import Evaluation
    engine = server.trust_engine_for("escort")
    engine.record_evaluation(Evaluation(
        evaluation_id="e1",
        evaluator_id="coach1",
        evaluatee_id=task.demander_id,
        ratings={"teaching_ability": 4.0, "patience": 4.0, "safety_record": 4.0},
        comment="",
    ))

    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 2.0

    profile = engine.evaluate(task.demander_id)
    # 原 4.0 - 2.0 = 2.0
    assert profile.overall_score == 2.0


def test_cancel_scheduled_with_deal_triggers_refund(app_client):
    """预约单已支付定金后取消，应触发退款。"""
    client, server = app_client
    scheduled_at = datetime.utcnow() + timedelta(hours=25)
    task = _create_scheduled_task(server, scheduled_at=scheduled_at)
    token = _login(client, server)

    # 模拟已选教练并支付（直接构造 deal + payment）
    from umcp_core.core.deal import Deal
    from umcp_core.shared.payment.mock import MockGateway
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    from umcp_core.shared.payment.service import PaymentService

    # 复用 server.payment_service（已在 register_plugin 中注册）
    payment_service = server.payment_service

    deal = Deal(
        task_id=task.task_id,
        resource_id="coach_res_1",
        demander_id=task.demander_id,
        supplier_id="coach1",
    )
    deal.bind_event_bus(server.event_bus)
    deal.final_amount = 100.0
    server.deal_repo.save(deal)

    # 创建并确认一笔定金支付
    intent = payment_service.create_payment(
        deal_id=deal.deal_id,
        user_id=task.demander_id,
        amount=30.0,
        payment_type="DEPOSIT",
    )
    payment_service.confirm_payment(payment_id=intent.payment_id)

    # 取消订单
    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # 验证退款（payment 记录状态变为 refunded）
    records = payment_service.repo.find_by_deal(deal.deal_id)
    refunded = [r for r in records if r["status"] == "refunded"]
    assert len(refunded) >= 1, "定金应被退款"


def test_cancel_nonexistent_task_returns_404(app_client):
    """取消不存在的订单返回 404。"""
    client, server = app_client
    token = _login(client, server)

    resp = client.post(
        "/api/v1/escort/orders/nonexistent/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_cancel_terminal_task_returns_409(app_client):
    """取消已终态的订单返回 409。"""
    client, server = app_client
    task = _create_realtime_task(server)
    task.bind_event_bus(server.event_bus)
    task.cancel()
    server.task_repo.save(task)

    token = _login(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task.task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_escort_cancel_policy.py -v`
预期：FAIL，`cancel_penalty` 字段不存在 / 测试断言失败。

- [ ] **步骤 3：扩展 OrderInfo 模型**

修改 `src/umcp_core/transport/routers/escort/orders.py` 的 `OrderInfo` 类（第 54-67 行），在末尾添加 `cancel_penalty` 字段：

```python
class OrderInfo(BaseModel):
    """订单信息（实时单/预约单通用）。"""

    task_id: str
    order_type: str
    status: str
    demander_id: str
    car_type: str
    duration_hours: int
    assigned_resource_id: str | None = None
    title: str | None = None
    scheduled_at: str | None = None
    coach_level_pref: str | None = None
    deal_id: str | None = None
    cancel_penalty: float = 0.0
```

- [ ] **步骤 4：实现罚分计算辅助函数**

在 `src/umcp_core/transport/routers/escort/orders.py` 的 `_task_to_order_info` 函数之后添加：

```python
def _calculate_scheduled_penalty(
    rule_config,
    scheduled_at: datetime | None,
    now: datetime | None = None,
) -> float:
    """根据预约单取消规则计算罚分。

    Args:
        rule_config: RuleConfig 实例（可为 None，返回 0）
        scheduled_at: 预约时间
        now: 当前时间（测试可注入），默认 datetime.utcnow()

    Returns:
        罚分分值（0.0 表示无罚分）
    """
    if rule_config is None or scheduled_at is None:
        return 0.0
    tiers = rule_config.get("escort.cancel.scheduled.penalty_tiers")
    if not tiers or not isinstance(tiers, list):
        return 0.0
    now = now or datetime.utcnow()
    hours_before = (scheduled_at - now).total_seconds() / 3600.0
    # 找到第一个 hours_before >= tier.hours_before 的档位
    for tier in tiers:
        if hours_before >= tier.get("hours_before", 0):
            return float(tier.get("penalty", 0.0))
    # 所有档位都不匹配（理论上最后 hours_before=0 档会兜底）
    return 0.0
```

- [ ] **步骤 5：重写 cancel_order 端点**

修改 `src/umcp_core/transport/routers/escort/orders.py` 的 `cancel_order`（第 206-221 行）：

```python
@router.post("/orders/{task_id}/cancel", response_model=Envelope)
async def cancel_order(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """学员取消订单。

    - 实时单：无罚分，直接 task.cancel()
    - 预约单：按规则梯度扣信用分；若已支付定金则触发退款
    """
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    if task.demander_id != current_user.user_id:
        raise PermissionDeniedError(message="只能取消自己的订单")

    rule_config = getattr(server, "rule_config", None)
    penalty = 0.0

    # 预约单：计算罚分并扣除信用分
    order_type = getattr(task, "order_type", None) or task.structured_fields.get("order_type")
    if order_type == "SCHEDULED":
        scheduled_at_str = task.structured_fields.get("scheduled_at")
        scheduled_at = None
        if scheduled_at_str:
            try:
                scheduled_at = datetime.fromisoformat(scheduled_at_str)
            except ValueError:
                scheduled_at = None
        penalty = _calculate_scheduled_penalty(rule_config, scheduled_at)
        if penalty > 0:
            engine = server.trust_engine_for(task.domain_tag.value)
            if engine is not None:
                engine.apply_penalty(
                    task.demander_id, penalty, reason="预约单取消"
                )

    # 取消 task
    task.bind_event_bus(server.event_bus)
    try:
        task.cancel()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 预约单：取消 deal 并退款
    if order_type == "SCHEDULED":
        deals = server.deal_repo.find_by_task(task_id)
        payment_service = getattr(server, "payment_service", None)
        for deal in deals:
            if deal.status in ("pending", "active"):
                deal.bind_event_bus(server.event_bus)
                try:
                    deal.cancel()
                    server.deal_repo.save(deal)
                except (RuntimeError, ValueError):
                    pass
            # 退款已支付的定金
            if payment_service is not None:
                records = payment_service.repo.find_by_deal(deal.deal_id)
                for record in records:
                    if record["status"] == "paid":
                        try:
                            payment_service.refund(
                                payment_id=record["payment_id"],
                                amount=record["amount"],
                                reason="学员取消预约单",
                            )
                        except Exception:
                            pass

    info = _task_to_order_info(task)
    info.cancel_penalty = penalty
    return ok(info.model_dump())
```

- [ ] **步骤 6：运行测试验证通过**

运行：`pytest tests/test_escort_cancel_policy.py -v`
预期：PASS

- [ ] **步骤 7：回归测试**

运行：`pytest tests/ -k "escort" -v`
预期：PASS（现有取消端点测试可能需要适配新字段，但 `cancel_penalty` 默认 0.0 不破坏现有断言）。

- [ ] **步骤 8：Commit**

```bash
git add tests/test_escort_cancel_policy.py src/umcp_core/transport/routers/escort/orders.py
git commit -m "feat(escort): cancel_order 端点按规则梯度扣信用分并触发退款"
```

---

### 任务 8：前端类型与取消规则 hook

**文件：**
- 修改：`web/src/types/escort.ts`
- 创建：`web/src/hooks/use-cancel-rules.ts`
- 测试：`web/tests/cancel-policy.test.ts`

- [ ] **步骤 1：编写失败的测试**

创建 `web/tests/cancel-policy.test.ts`：

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useCancelRules } from "@/hooks/use-cancel-rules";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client");

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useCancelRules", () => {
  beforeEach(() => vi.clearAllMocks());

  it("应获取取消规则", async () => {
    (apiClient.get as any).mockResolvedValue({
      timeout_seconds: 60,
      expand_after_seconds: 30,
      penalty_tiers: [
        { hours_before: 24, penalty: 0.2 },
        { hours_before: 0, penalty: 2.0 },
      ],
    });
    const { result } = renderHook(() => useCancelRules(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.timeout_seconds).toBe(60);
    expect(result.current.data?.penalty_tiers).toHaveLength(2);
  });

  it("应提供 calculatePenalty 函数", async () => {
    (apiClient.get as any).mockResolvedValue({
      timeout_seconds: 60,
      expand_after_seconds: 30,
      penalty_tiers: [
        { hours_before: 24, penalty: 0.2 },
        { hours_before: 12, penalty: 0.5 },
        { hours_before: 0, penalty: 2.0 },
      ],
    });
    const { result } = renderHook(() => useCancelRules(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const now = new Date("2026-08-03T10:00:00Z");
    // 提前 25 小时 → 命中 hours_before=24 档 → 0.2
    const far = new Date("2026-08-04T11:00:00Z");
    expect(result.current.calculatePenalty(far, now)).toBe(0.2);
    // 提前 1 小时 → 命中 hours_before=0 档 → 2.0
    const near = new Date("2026-08-03T11:00:00Z");
    expect(result.current.calculatePenalty(near, now)).toBe(2.0);
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd web && npx vitest run tests/cancel-policy.test.ts`
预期：FAIL，`Cannot find module '@/hooks/use-cancel-rules'`。

- [ ] **步骤 3：扩展类型定义**

修改 `web/src/types/escort.ts`，在 `OrderInfo` 接口末尾添加 `cancel_penalty` 字段，并新增 `CancelRules` 接口：

```typescript
/** 订单信息。 */
export interface OrderInfo {
  task_id: string;
  order_type: string;
  status: OrderStatus;
  demander_id: string;
  car_type: string;
  duration_hours: number;
  assigned_resource_id: string | null;
  title: string | null;
  scheduled_at?: string | null;
  coach_level_pref?: string | null;
  deal_id?: string | null;
  cancel_penalty?: number;
}

/** 取消规则配置。 */
export interface CancelRules {
  timeout_seconds: number;
  expand_after_seconds: number;
  penalty_tiers: PenaltyTier[];
}

/** 罚分梯度档位。 */
export interface PenaltyTier {
  hours_before: number;
  penalty: number;
}
```

- [ ] **步骤 4：实现 use-cancel-rules hook**

创建 `web/src/hooks/use-cancel-rules.ts`：

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { CancelRules, PenaltyTier } from "@/types/escort";

/** 获取取消规则（实时单超时、预约单罚分梯度）。 */
export function useCancelRules() {
  const query = useQuery({
    queryKey: ["cancel-rules"],
    queryFn: () => apiClient.get<CancelRules>("/escort/cancel-rules"),
    staleTime: 5 * 60 * 1000, // 5 分钟缓存
  });

  const calculatePenalty = (
    scheduledAt: Date | string | null,
    now: Date = new Date(),
  ): number => {
    if (!scheduledAt || !query.data) return 0;
    const scheduled = typeof scheduledAt === "string" ? new Date(scheduledAt) : scheduledAt;
    const hoursBefore = (scheduled.getTime() - now.getTime()) / 3600000;
    const tiers = query.data.penalty_tiers ?? [];
    for (const tier of tiers) {
      if (hoursBefore >= tier.hours_before) {
        return tier.penalty;
      }
    }
    return 0;
  };

  return {
    ...query,
    calculatePenalty,
  };
}
```

- [ ] **步骤 5：运行测试验证通过**

运行：`cd web && npx vitest run tests/cancel-policy.test.ts`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add web/src/types/escort.ts web/src/hooks/use-cancel-rules.ts web/tests/cancel-policy.test.ts
git commit -m "feat(web): 新增 useCancelRules hook 与取消规则类型"
```

---

### 任务 9：后端新增 cancel-rules 查询端点

**文件：**
- 修改：`src/umcp_core/transport/routers/escort/orders.py`
- 测试：`tests/test_escort_cancel_rules_endpoint.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_escort_cancel_rules_endpoint.py`：

```python
"""验证 /api/v1/escort/cancel-rules 端点返回取消规则。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _token(server, user_id="student1") -> str:
    from umcp_core.core.base import User
    from umcp_core.core.domain import DomainTag
    from umcp_core.transport.auth import JwtService, make_claims

    jwt_service = JwtService(secret="test-secret")
    user = User(
        user_id=user_id,
        name=user_id,
        domain_tags=[DomainTag.of("escort")],
        roles=["demander"],
    )
    return jwt_service.encode(make_claims(user))


def test_get_cancel_rules(app_client):
    """应返回默认取消规则。"""
    client, server = app_client
    token = _token(server)
    resp = client.get(
        "/api/v1/escort/cancel-rules",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["timeout_seconds"] == 60
    assert data["expand_after_seconds"] == 30
    assert data["penalty_tiers"] == [
        {"hours_before": 24, "penalty": 0.2},
        {"hours_before": 12, "penalty": 0.5},
        {"hours_before": 4, "penalty": 1.0},
        {"hours_before": 0, "penalty": 2.0},
    ]


def test_get_cancel_rules_reflects_overrides(app_client):
    """运营覆盖规则后端点应返回新值。"""
    client, server = app_client
    server.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=120,
        updated_by="admin",
        category="escort.cancel",
    )
    token = _token(server)
    resp = client.get(
        "/api/v1/escort/cancel-rules",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["timeout_seconds"] == 120
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_escort_cancel_rules_endpoint.py -v`
预期：FAIL，404。

- [ ] **步骤 3：实现 cancel-rules 端点**

在 `src/umcp_core/transport/routers/escort/orders.py` 的 `cancel_order` 端点之后添加：

```python
@router.get("/cancel-rules", response_model=Envelope)
async def get_cancel_rules(
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """返回当前取消规则配置（供前端倒计时与罚分提示）。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")

    class CancelRules(BaseModel):
        timeout_seconds: int
        expand_after_seconds: int
        penalty_tiers: list[dict[str, Any]]

    return ok(
        CancelRules(
            timeout_seconds=rule_config.get("escort.cancel.realtime.timeout_seconds", default=60),
            expand_after_seconds=rule_config.get("escort.cancel.realtime.expand_after_seconds", default=30),
            penalty_tiers=rule_config.get("escort.cancel.scheduled.penalty_tiers", default=[]),
        ).model_dump()
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_escort_cancel_rules_endpoint.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add tests/test_escort_cancel_rules_endpoint.py src/umcp_core/transport/routers/escort/orders.py
git commit -m "feat(escort): 新增 /cancel-rules 端点供前端查询取消规则"
```

---

### 任务 10：前端倒计时与取消对话框组件

**文件：**
- 创建：`web/src/components/countdown-timer.tsx`
- 创建：`web/src/components/cancel-dialog.tsx`
- 测试：`web/tests/cancel-components.test.tsx`

- [ ] **步骤 1：编写失败的测试**

创建 `web/tests/cancel-components.test.tsx`：

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CountdownTimer } from "@/components/countdown-timer";
import { CancelDialog } from "@/components/cancel-dialog";

describe("CountdownTimer", () => {
  it("应显示剩余秒数", () => {
    const now = new Date("2026-08-03T10:00:00Z");
    const created = new Date("2026-08-03T10:00:30Z"); // 30 秒前下单
    vi.useFakeTimers().setSystemTime(now);
    render(<CountdownTimer createdAt={created} timeoutSeconds={60} />);
    // 剩余 30 秒
    expect(screen.getByText(/30/)).toBeTruthy();
    vi.useRealTimers();
  });

  it("超时后应显示已超时", () => {
    const now = new Date("2026-08-03T10:02:00Z");
    const created = new Date("2026-08-03T10:00:00Z"); // 120 秒前下单
    vi.useFakeTimers().setSystemTime(now);
    render(<CountdownTimer createdAt={created} timeoutSeconds={60} />);
    expect(screen.getByText(/已超时/)).toBeTruthy();
    vi.useRealTimers();
  });
});

describe("CancelDialog", () => {
  it("实时单不显示罚分提示", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <CancelDialog
        open={true}
        orderType="REALTIME"
        penalty={0}
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    expect(screen.queryByText(/扣/)).toBeNull();
    expect(screen.getByText(/确认取消/)).toBeTruthy();
  });

  it("预约单显示罚分提示", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <CancelDialog
        open={true}
        orderType="SCHEDULED"
        penalty={2.0}
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    expect(screen.getByText(/扣.*2.*分/)).toBeTruthy();
  });

  it("点击确认调用 onConfirm", async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <CancelDialog
        open={true}
        orderType="REALTIME"
        penalty={0}
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /确认取消/ }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalled());
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd web && npx vitest run tests/cancel-components.test.tsx`
预期：FAIL，`Cannot find module '@/components/countdown-timer'`。

- [ ] **步骤 3：实现 CountdownTimer 组件**

创建 `web/src/components/countdown-timer.tsx`：

```typescript
"use client";

import { useEffect, useState } from "react";

interface CountdownTimerProps {
  /** 下单时间（ISO 字符串或 Date）。 */
  createdAt: string | Date;
  /** 超时秒数。 */
  timeoutSeconds: number;
  /** 超时回调（可选）。 */
  onTimeout?: () => void;
}

export function CountdownTimer({ createdAt, timeoutSeconds, onTimeout }: CountdownTimerProps) {
  const created = typeof createdAt === "string" ? new Date(createdAt) : createdAt;
  const [remaining, setRemaining] = useState<number>(
    Math.max(0, timeoutSeconds - (Date.now() - created.getTime()) / 1000),
  );

  useEffect(() => {
    const timer = setInterval(() => {
      const r = timeoutSeconds - (Date.now() - created.getTime()) / 1000;
      setRemaining(Math.max(0, r));
      if (r <= 0 && onTimeout) onTimeout();
    }, 1000);
    return () => clearInterval(timer);
  }, [created, timeoutSeconds, onTimeout]);

  if (remaining <= 0) {
    return <span className="text-red-500 text-sm">已超时</span>;
  }
  return (
    <span className="text-orange-500 text-sm">
      剩余 {Math.ceil(remaining)} 秒
    </span>
  );
}
```

- [ ] **步骤 4：实现 CancelDialog 组件**

创建 `web/src/components/cancel-dialog.tsx`：

```typescript
"use client";

import { Button } from "@/components/ui/button";

interface CancelDialogProps {
  open: boolean;
  orderType: "REALTIME" | "SCHEDULED";
  penalty: number;
  onConfirm: () => void;
  onClose: () => void;
}

export function CancelDialog({
  open,
  orderType,
  penalty,
  onConfirm,
  onClose,
}: CancelDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-sm w-full mx-4 space-y-4">
        <h3 className="text-lg font-medium">确认取消</h3>
        <p className="text-sm text-gray-600">
          {orderType === "REALTIME"
            ? "取消后将通知在线教练。"
            : `取消将扣除信用分 ${penalty} 分，已支付定金将原路退回。`}
        </p>
        {orderType === "SCHEDULED" && penalty > 0 && (
          <p className="text-xs text-orange-600">
            提示：越临近预约时间取消，扣分越多。
          </p>
        )}
        <div className="flex gap-2 justify-end">
          <Button variant="ghost" onClick={onClose}>
            再想想
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            确认取消
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **步骤 5：运行测试验证通过**

运行：`cd web && npx vitest run tests/cancel-components.test.tsx`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add web/src/components/countdown-timer.tsx web/src/components/cancel-dialog.tsx web/tests/cancel-components.test.tsx
git commit -m "feat(web): 新增倒计时与取消确认对话框组件"
```

---

### 任务 11：集成到学员端订单详情页

**文件：**
- 修改：`web/src/app/(protected)/escort/student/orders/[id]/page.tsx`
- 测试：`web/tests/student-order-detail-cancel.test.tsx`（轻量渲染测试）

- [ ] **步骤 1：编写失败的测试**

创建 `web/tests/student-order-detail-cancel.test.tsx`：

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import StudentOrderDetail from "@/app/(protected)/escort/student/orders/[id]/page";

// mock 路由参数与 hooks
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "task_1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/auth-store", () => ({
  useAuthStore: () => ({ user: { user_id: "student1" } }),
}));

vi.mock("@/hooks/use-orders", () => ({
  useOrder: () => ({
    data: {
      task_id: "task_1",
      order_type: "REALTIME",
      status: "published",
      demander_id: "student1",
      car_type: "auto",
      duration_hours: 1,
      cancel_penalty: 0,
    },
    isLoading: false,
  }),
  useReviews: () => ({ data: [] }),
  useInvalidateOrder: () => vi.fn(),
}));

vi.mock("@/hooks/use-cancel-rules", () => ({
  useCancelRules: () => ({
    data: {
      timeout_seconds: 60,
      expand_after_seconds: 30,
      penalty_tiers: [],
    },
    calculatePenalty: () => 0,
  }),
}));

vi.mock("@/hooks/use-scheduled", () => ({
  useDeal: () => ({ data: null }),
}));

vi.mock("@/hooks/use-ws-events", () => ({
  useWsEvent: () => {},
}));

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({}),
  },
}));

describe("StudentOrderDetail 取消功能", () => {
  it("实时单 published 状态应显示倒计时与取消按钮", () => {
    render(<StudentOrderDetail />);
    expect(screen.getByText(/剩余/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /取消订单/ })).toBeTruthy();
  });

  it("点击取消按钮应弹出确认对话框", async () => {
    render(<StudentOrderDetail />);
    fireEvent.click(screen.getByRole("button", { name: /取消订单/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /确认取消/ })).toBeTruthy(),
    );
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd web && npx vitest run tests/student-order-detail-cancel.test.tsx`
预期：FAIL，组件未集成倒计时与取消对话框。

- [ ] **步骤 3：集成到学员端订单详情页**

修改 `web/src/app/(protected)/escort/student/orders/[id]/page.tsx`，在文件顶部导入区添加：

```typescript
import { useCancelRules } from "@/hooks/use-cancel-rules";
import { CountdownTimer } from "@/components/countdown-timer";
import { CancelDialog } from "@/components/cancel-dialog";
```

在组件函数体内（在其他 useState 附近）添加：

```typescript
  const cancelRules = useCancelRules();
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const scheduledPenalty = cancelRules.calculatePenalty(order?.scheduled_at ?? null);
```

在实时单 `published` 状态的 UI 区域（loading 判断之后、return JSX 中）添加倒计时与取消按钮。在 JSX 的订单信息卡片之后添加：

```typescript
        {/* 实时单：published 状态显示倒计时 */}
        {order.order_type === "REALTIME" && order.status === "published" && (
          <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-orange-800">等待教练抢单</span>
              <CountdownTimer
                createdAt={order.created_at ?? new Date().toISOString()}
                timeoutSeconds={cancelRules.data?.timeout_seconds ?? 60}
              />
            </div>
          </div>
        )}

        {/* 取消按钮（非终态均可显示） */}
        {order.status !== "completed" && order.status !== "cancelled" && (
          <Button
            variant="outline"
            className="w-full text-red-600 border-red-300"
            onClick={() => setShowCancelDialog(true)}
          >
            取消订单
          </Button>
        )}

        <CancelDialog
          open={showCancelDialog}
          orderType={order.order_type as "REALTIME" | "SCHEDULED"}
          penalty={order.order_type === "SCHEDULED" ? scheduledPenalty : 0}
          onConfirm={async () => {
            await apiClient.post(`/escort/orders/${taskId}/cancel`, {});
            setShowCancelDialog(false);
            invalidate();
          }}
          onClose={() => setShowCancelDialog(false)}
        />
```

注意：`order.created_at` 字段当前 `OrderInfo` 类型中不存在。需在 `web/src/types/escort.ts` 的 `OrderInfo` 接口中添加 `created_at?: string` 字段，并在后端 `_task_to_order_info` 中填充。为最小化改动，前端倒计时使用 `order.created_at ?? new Date().toISOString()` 兜底（后端未返回时按当前时间算，倒计时显示满额）。

为支持倒计时准确，扩展后端 `OrderInfo` 与 `_task_to_order_info`：

在 `src/umcp_core/transport/routers/escort/orders.py` 的 `OrderInfo` 类中添加 `created_at: str | None = None` 字段；在 `_task_to_order_info` 函数中添加 `created_at=task.created_at.isoformat()`。

- [ ] **步骤 4：运行测试验证通过**

运行：`cd web && npx vitest run tests/student-order-detail-cancel.test.tsx`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add web/src/app/\(protected\)/escort/student/orders/\[id\]/page.tsx web/src/types/escort.ts web/tests/student-order-detail-cancel.test.tsx src/umcp_core/transport/routers/escort/orders.py
git commit -m "feat(web): 学员端订单详情页集成倒计时与取消对话框"
```

---

### 任务 12：教练端监听 task.cancelled 事件

**文件：**
- 修改：`web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`

- [ ] **步骤 1：修改教练端订单详情页**

修改 `web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`，在现有 `useWsEvent` 调用区域（第 32-36 行附近）确认包含 `task.cancelled` 监听。当前已有：

```typescript
  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());
  useWsEvent("deal.confirmed", () => invalidate());
  useWsEvent("deal.rejected", () => invalidate());
  useWsEvent("payment.paid", () => invalidate());
```

`task.cancelled` 已存在，无需修改。但需在 UI 中显示已取消状态。在订单信息卡片的状态显示区域之后添加：

```typescript
        {order.status === "cancelled" && (
          <div className="bg-gray-100 border border-gray-300 rounded-lg p-4 text-center">
            <p className="text-gray-700">订单已取消</p>
          </div>
        )}
```

- [ ] **步骤 2：验证前端测试通过**

运行：`cd web && npx vitest run`
预期：PASS

- [ ] **步骤 3：Commit**

```bash
git add web/src/app/\(protected\)/escort/coach/orders/\[id\]/page.tsx
git commit -m "feat(web): 教练端订单详情页显示已取消状态"
```

---

### 任务 13：端到端集成测试

**文件：**
- 创建：`tests/test_escort_cancel_e2e.py`

- [ ] **步骤 1：编写端到端测试**

创建 `tests/test_escort_cancel_e2e.py`：

```python
"""取消策略端到端集成测试。

覆盖：
1. 实时单：超时自动取消（SchedulerService 驱动）
2. 实时单：用户手动取消（无罚分）
3. 预约单：提前 25h 取消（扣 0.2 分 + 退款）
4. 预约单：提前 1h 取消（扣 2.0 分 + 退款）
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from umcp_core.core.domain import DomainTag
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.workers.realtime_cancel_worker import RealtimeCancelWorker


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    # 加速测试：超时 2 秒，扩展 1 秒
    server.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=2,
        updated_by="test",
        category="escort.cancel",
    )
    server.rule_config.set(
        key="escort.cancel.realtime.expand_after_seconds",
        value=1,
        updated_by="test",
        category="escort.cancel",
    )
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _token(server, user_id="student1") -> str:
    from umcp_core.core.base import User
    from umcp_core.transport.auth import JwtService, make_claims

    jwt_service = JwtService(secret="test-secret")
    user = User(
        user_id=user_id,
        name=user_id,
        domain_tags=[DomainTag.of("escort")],
        roles=["demander"],
    )
    return jwt_service.encode(make_claims(user))


def _create_realtime_order(client, server, user_id="student1") -> str:
    """通过 API 下实时单，返回 task_id。"""
    token = _token(server, user_id)
    resp = client.post(
        "/api/v1/escort/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "demander_id": user_id,
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "auto",
            "required_skills": [],
            "duration_hours": 1,
            "order_type": "REALTIME",
        },
    )
    assert resp.status_code == 200
    return resp.json()["data"]["task_id"]


@pytest.mark.asyncio
async def test_e2e_realtime_auto_cancel(app_client):
    """实时单超时后应被 SchedulerService 自动取消。"""
    client, server = app_client
    task_id = _create_realtime_order(client, server)

    # 手动驱动 worker（不依赖 lifespan 中的 1 秒间隔）
    worker = RealtimeCancelWorker()
    # 第 0 秒：未超时
    await worker.run(context={"server": server})
    assert server.task_repo.find_by_id(task_id).status == "published"

    # 等待 2.5 秒（超过 2 秒超时）
    await asyncio.sleep(2.5)
    await worker.run(context={"server": server})

    refreshed = server.task_repo.find_by_id(task_id)
    assert refreshed.status == "cancelled"


def test_e2e_realtime_manual_cancel_no_penalty(app_client):
    """实时单手动取消不扣信用分。"""
    client, server = app_client
    task_id = _create_realtime_order(client, server)
    token = _token(server)

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "cancelled"
    assert body["cancel_penalty"] == 0.0


def test_e2e_scheduled_cancel_far_advance_low_penalty(app_client):
    """预约单提前 25h 取消，扣 0.2 分。"""
    client, server = app_client
    token = _token(server)
    scheduled_at = (datetime.utcnow() + timedelta(hours=25)).isoformat()

    # 下预约单
    resp = client.post(
        "/api/v1/escort/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "demander_id": "student1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "auto",
            "required_skills": [],
            "duration_hours": 1,
            "order_type": "SCHEDULED",
            "scheduled_at": scheduled_at,
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]

    # 取消
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 0.2


def test_e2e_scheduled_cancel_close_high_penalty(app_client):
    """预约单提前 1h 取消，扣 2.0 分。"""
    client, server = app_client
    token = _token(server)
    scheduled_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()

    # 先给学员正向评分（4.0）
    engine = server.trust_engine_for("escort")
    engine.record_evaluation(Evaluation(
        evaluation_id="e1",
        evaluator_id="coach1",
        evaluatee_id="student1",
        ratings={"teaching_ability": 4.0, "patience": 4.0, "safety_record": 4.0},
        comment="",
    ))

    resp = client.post(
        "/api/v1/escort/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "demander_id": "student1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "auto",
            "required_skills": [],
            "duration_hours": 1,
            "order_type": "SCHEDULED",
            "scheduled_at": scheduled_at,
        },
    )
    task_id = resp.json()["data"]["task_id"]

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancel_penalty"] == 2.0

    # 信用分应为 4.0 - 2.0 = 2.0
    profile = engine.evaluate("student1")
    assert profile.overall_score == 2.0
```

- [ ] **步骤 2：运行端到端测试**

运行：`pytest tests/test_escort_cancel_e2e.py -v`
预期：PASS

- [ ] **步骤 3：全量回归测试**

运行：`pytest tests/ -v 2>&1 | tail -30`
预期：全部 PASS（或仅已知技术债相关 skip）。

运行：`cd web && npx vitest run 2>&1 | tail -20`
预期：全部 PASS。

- [ ] **步骤 4：Commit**

```bash
git add tests/test_escort_cancel_e2e.py
git commit -m "test(escort): 取消策略端到端集成测试"
```

---

## 自检

### 1. 规格覆盖度

| 规格需求 | 实现任务 |
|---------|---------|
| 实时单超时自动取消 | 任务 5（RealtimeCancelWorker）+ 任务 6（lifespan 启动）+ 任务 13（E2E） |
| 实时单超时增加搜索范围 | 任务 5（扩展搜索广播） |
| 实时单用户手动取消 | 任务 7（cancel_order 端点，无罚分）+ 任务 13（E2E） |
| 预约单用户手动取消扣信用值 | 任务 7（按梯度扣分）+ 任务 13（E2E） |
| 规则可由管理员配置 | 任务 3（RuleConfig 注册 + 默认值）+ 任务 9（查询端点） |
| 前端倒计时 UI | 任务 10（CountdownTimer）+ 任务 11（集成） |
| 前端取消确认 UI | 任务 10（CancelDialog）+ 任务 11（集成） |
| WS 推送 task.cancelled | 任务 1（修复 Task.cancel 事件）+ 任务 12（教练端监听） |
| 预约单取消退款 | 任务 7（cancel_order 内退款逻辑）+ 任务 13（E2E） |

覆盖完整，无遗漏。

### 2. 占位符扫描

无 "TODO"、"待定"、"后续实现" 等占位符。每个步骤都包含完整代码。

### 3. 类型一致性

- `cancel_penalty` 字段：后端 `OrderInfo.cancel_penalty: float = 0.0`（任务 7），前端 `OrderInfo.cancel_penalty?: number`（任务 8）—— 一致。
- `CancelRules` 类型：后端返回 `{timeout_seconds, expand_after_seconds, penalty_tiers}`（任务 9），前端 `CancelRules` 接口（任务 8）—— 一致。
- `apply_penalty(user_id, points, reason)`：任务 2 定义，任务 7 调用 —— 一致。
- `RealtimeCancelWorker.run(context)`：任务 4 定义 `Worker` 协议，任务 5 实现，任务 6 注册 —— 一致。
- `calculatePenalty(scheduledAt, now)`：任务 8 定义，任务 11 调用 —— 一致。

---

## 执行交接

**计划已完成并保存到 `docs/plans/2026-08-03-escort-cancel-policy.md`。两种执行方式：**

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**
