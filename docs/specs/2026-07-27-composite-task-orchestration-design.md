# 阶段四 C：复合任务编排 设计规格

**日期**：2026-07-27
**状态**：已确认，待编写实现计划
**前置**：阶段四 B（跨域身份与信用，已实现，commit `8463835`）
**后续**：无（阶段四收官）

## 1. 目标与范围

### 1.1 目标

让一个父任务（`CompositeTask`）可以包含跨多个 domain 的子任务，子任务通过
`depends_on` 声明 DAG 依赖，由现有 EventBus 驱动状态转移，失败按依赖传播。

**核心场景**：商务出行包 = 打车（ride 域）+ 代驾（escort 域）+ 团购伴手礼
（group_buying 域）。代驾依赖打车先完成，团购与打车并行。父任务等所有子任务
终态化后自动 COMPLETED 或 CANCELLED。

### 1.2 端到端验证锚点

同一 UMCPServer 实例加载三个插件，创建 CompositeTask：
- 子任务 A：打车去机场（ride 域，无依赖）
- 子任务 B：代驾回家（escort 域，depends_on=[A]）
- 子任务 C：团购伴手礼（group_buying 域，无依赖）

预期：
- A 与 C 并行启动，B 等待 A 完成
- A 完成 → B 就绪启动
- B、C 完成 → 父任务 COMPLETED
- 若 A 失败 → B 取消，C 不受影响继续完成 → 父任务 CANCELLED

### 1.3 不在本阶段范围

- 跨域资源（一个资源同时属于多个 domain）
- 子任务间数据传递（前一个的输出作为后一个的输入）—— 当前仅状态依赖
- 复合任务持久化与恢复 —— 当前仅内存态
- 子任务超时自动取消
- 复合任务进度查询索引 API —— 可通过遍历 subtasks 状态实现

## 2. 核心决策

| 决策点 | 选择 | 说明 |
|--------|------|------|
| 编排职责 | 事件驱动状态机 | 通过现有 EventBus 驱动，不引入显式 Orchestrator |
| 执行模式 | DAG，子任务声明 depends_on | 支持并行与串行混合 |
| 失败策略 | 按依赖传播失败 | 失败子任务 → 下游取消，无依赖兄弟继续 |
| 父任务模型 | 新增 CompositeTask 继承 PackageTask | 复用现有抽象，TenderTask 可平滑兼容 |
| 子任务执行 | 按 domain_tag 路由到对应插件 | 阶段四A/B 已支持，子任务自治 |
| 事件桥接 | EventBus 订阅 TASK_COMPLETED 桥接到 SUBTASK_* | 不修改子任务类 |
| 扩展点 | register_subtask_executor | 允许插件覆盖默认执行路径 |

## 3. 核心库改动

### 3.1 `src/umcp_core/core/task.py` — 新增 CompositeTask

```python
class CompositeTask(PackageTask):
    """跨 domain 复合任务（DAG 编排）。

    子任务可通过 dependencies 声明依赖关系，形成 DAG。
    状态转移由事件驱动：子任务 COMPLETED/CANCELLED 触发父任务状态更新。
    """

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,  # 父任务标识域，不参与子任务路由
        subtasks: list[Task] | None = None,
        dependencies: dict[str, list[str]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(demander_id, domain_tag, **kwargs)
        # subtasks 统一存储（合并 standard + custom，便于 DAG 操作）
        self.subtasks: list[Task] = subtasks or []
        # 依赖映射：subtask_id → [depends_on_subtask_id, ...]
        self.dependencies: dict[str, list[str]] = dependencies or {}
        # 同步到 PackageTask 字段（向后兼容 TenderTask 的访问路径）
        self._sync_to_package_fields()
        # DAG 校验（构造时即拒绝非法拓扑）
        self._validate_dag()

    def task_type(self) -> str:
        return "composite"

    # ---- DAG 查询接口 ----

    def ready_subtasks(self) -> list[Task]:
        """返回当前可执行的子任务（依赖已全部 COMPLETED 且自身未启动）。"""
        ready = []
        for sub in self.subtasks:
            if sub.status != TaskStatus.DRAFT:
                continue
            deps = self.dependencies.get(sub.task_id, [])
            if all(self._find_sub(d).status == TaskStatus.COMPLETED for d in deps):
                ready.append(sub)
        return ready

    def pending_subtasks(self) -> list[Task]:
        """返回尚未完成的子任务（非终态）。"""
        return [s for s in self.subtasks if not TaskStatus.is_terminal(s.status)]

    def descendants(self, subtask_id: str) -> list[str]:
        """返回直接或间接依赖 subtask_id 的所有下游子任务 ID（用于失败传播）。"""
        reverse = self._build_reverse_deps()
        visited, result = set(), []
        queue = [subtask_id]
        while queue:
            current = queue.pop(0)
            for child in reverse.get(current, []):
                if child not in visited:
                    visited.add(child)
                    result.append(child)
                    queue.append(child)
        return result

    # ---- 事件订阅与状态转移 ----

    def bind_event_bus(self, bus: EventBus) -> None:
        """绑定事件总线并订阅子任务事件。"""
        super().bind_event_bus(bus)
        self._event_bus.subscribe(EventType.SUBTASK_COMPLETED, self._on_subtask_completed)
        self._event_bus.subscribe(EventType.SUBTASK_CANCELLED, self._on_subtask_cancelled)

    def emit_subtask_event(self, subtask: Task, event_type: EventType) -> None:
        """子任务状态变更时由上层（server/桥接）调用，通知父任务。"""
        if self._event_bus is None:
            return
        from umcp_core.events.bus import Event
        self._event_bus.publish(Event(
            type=event_type,
            source_layer="L2",
            payload={
                "composite_task_id": self.task_id,
                "subtask_id": subtask.task_id,
                "subtask_domain": subtask.domain_tag.value,
                "subtask_status": subtask.status,
            },
        ))

    def _on_subtask_completed(self, event: Event) -> None:
        """子任务完成回调：检查是否所有子任务完成 → 父任务 complete。"""
        if event.payload.get("composite_task_id") != self.task_id:
            return
        if any(not TaskStatus.is_terminal(s.status) for s in self.subtasks):
            return
        if any(s.status == TaskStatus.CANCELLED for s in self.subtasks):
            self._fail_composite()
        else:
            self._complete_composite()

    def _on_subtask_cancelled(self, event: Event) -> None:
        """子任务取消回调：传播取消到下游子任务。"""
        if event.payload.get("composite_task_id") != self.task_id:
            return
        failed_id = event.payload.get("subtask_id")
        downstream_ids = self.descendants(failed_id)
        for sub_id in downstream_ids:
            sub = self._find_sub(sub_id)
            if not TaskStatus.is_terminal(sub.status):
                sub.cancel()
                self.emit_subtask_event(sub, EventType.SUBTASK_CANCELLED)
        self._on_subtask_completed(event)

    def _complete_composite(self) -> None:
        """所有子任务成功完成 → 父任务完成。"""
        if self.status == TaskStatus.COMPLETED:
            return
        Task.complete(self)  # 跳过 PackageTask.complete 避免重复校验
        if self._event_bus:
            from umcp_core.events.bus import Event
            self._event_bus.publish(Event(
                type=EventType.COMPOSITE_COMPLETED,
                source_layer="L2",
                payload={"composite_task_id": self.task_id},
            ))

    def _fail_composite(self) -> None:
        """存在失败子任务 → 父任务失败。"""
        if self.status == TaskStatus.CANCELLED:
            return
        self.cancel()
        if self._event_bus:
            from umcp_core.events.bus import Event
            self._event_bus.publish(Event(
                type=EventType.COMPOSITE_FAILED,
                source_layer="L2",
                payload={
                    "composite_task_id": self.task_id,
                    "failed_subtask_ids": [
                        s.task_id for s in self.subtasks
                        if s.status == TaskStatus.CANCELLED
                    ],
                },
            ))

    # ---- DAG 校验 ----

    def _validate_dag(self) -> None:
        """构造时校验 DAG 合法性：无环、引用存在、无自环。"""
        sub_ids = {s.task_id for s in self.subtasks}
        for sub_id, deps in self.dependencies.items():
            if sub_id not in sub_ids:
                raise ValueError(f"依赖键 {sub_id} 不在子任务列表中")
            for d in deps:
                if d not in sub_ids:
                    raise ValueError(f"依赖目标 {d} 不在子任务列表中")
                if d == sub_id:
                    raise ValueError(f"子任务 {sub_id} 不能依赖自身")
        # 环检测（DFS）
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {sid: WHITE for sid in sub_ids}
        def dfs(node: str) -> None:
            color[node] = GRAY
            for dep in self.dependencies.get(node, []):
                if color[dep] == GRAY:
                    raise ValueError(f"检测到环：{node} → {dep}")
                if color[dep] == WHITE:
                    dfs(dep)
            color[node] = BLACK
        for sid in sub_ids:
            if color[sid] == WHITE:
                dfs(sid)

    # ---- 内部辅助 ----

    def _find_sub(self, subtask_id: str) -> Task:
        for sub in self.subtasks:
            if sub.task_id == subtask_id:
                return sub
        raise KeyError(f"子任务 {subtask_id} 不存在")

    def _build_reverse_deps(self) -> dict[str, list[str]]:
        reverse: dict[str, list[str]] = {}
        for sub_id, deps in self.dependencies.items():
            for d in deps:
                reverse.setdefault(d, []).append(sub_id)
        return reverse

    def _sync_to_package_fields(self) -> None:
        """同步 subtasks 到 PackageTask 的 standard_sub_tasks / custom_sub_task。"""
        self.standard_sub_tasks = [s for s in self.subtasks if isinstance(s, StandardTask)]
        customs = [s for s in self.subtasks if isinstance(s, CustomTask)]
        self.custom_sub_task = customs[0] if customs else None
```

**关键设计点**：
1. `subtasks` 统一存储，便于 DAG 遍历；`_sync_to_package_fields` 保持向后兼容
2. 构造时 DAG 校验（环、自环、引用不存在）fail-fast
3. `ready_subtasks()` / `descendants()` 为事件驱动状态转移提供查询
4. `complete()` 不直接调用，由事件驱动 `_complete_composite`

### 3.2 `src/umcp_core/events/types.py` — 新增事件类型

```python
class EventType:
    # ... 现有事件 ...
    SUBTASK_COMPLETED = "subtask.completed"      # 子任务完成
    SUBTASK_CANCELLED = "subtask.cancelled"      # 子任务取消
    COMPOSITE_COMPLETED = "composite.completed"  # 复合任务整体完成
    COMPOSITE_FAILED = "composite.failed"        # 复合任务整体失败
```

**为什么需要 SUBTASK_* 事件**：现有 `TASK_COMPLETED` 的 payload 只含 `task_id`，
无法快速区分是否属于某复合任务的子任务。SUBTASK_* 事件携带
`composite_task_id`，父任务回调通过该字段过滤，避免全量扫描。

### 3.3 `src/umcp_core/server.py` — UMCPServer 编排路由

```python
class UMCPServer:
    def __init__(self) -> None:
        # ... 既有字段 ...
        self._subtask_executors: dict[str, Callable[[Task], None]] = {}

    # ------------------------------------------------------------------
    # 复合任务编排
    # ------------------------------------------------------------------

    def execute_composite(self, composite: CompositeTask) -> None:
        """驱动复合任务执行。

        流程：
        1. 绑定 EventBus（订阅子任务事件）
        2. 发布父任务 → 进入 MATCHING
        3. 按 DAG 拓扑序启动就绪子任务
        4. 每个子任务按各自 domain_tag 路由到对应插件执行
        5. 子任务完成事件触发父任务状态转移（由 CompositeTask 事件回调处理）

        本方法只负责"启动"，不负责"完成判定"——完成判定由事件驱动。
        """
        from umcp_core.core.task import CompositeTask, TaskStatus
        if not isinstance(composite, CompositeTask):
            raise TypeError(f"期望 CompositeTask，收到 {type(composite).__name__}")
        if composite.status != TaskStatus.DRAFT:
            raise RuntimeError(f"复合任务状态 {composite.status} 不允许执行")

        composite.bind_event_bus(self.event_bus)
        composite.publish()

        # 注册子任务事件桥接：TASK_COMPLETED → SUBTASK_*
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
            # 注意：emit_subtask_event 是同步的，此时 _on_subtask_* 已执行完毕
            self._dispatch_ready_subtasks(composite)

        self.event_bus.subscribe(EventType.TASK_COMPLETED, _bridge_to_subtask_event)

        # 启动所有就绪子任务
        self._dispatch_ready_subtasks(composite)

    def _dispatch_ready_subtasks(self, composite: CompositeTask) -> None:
        """派发就绪子任务到对应 domain 执行。"""
        for subtask in composite.ready_subtasks():
            subtask.bind_event_bus(self.event_bus)
            subtask.publish()
            self._execute_subtask_by_domain(subtask)

    def _execute_subtask_by_domain(self, subtask: Task) -> None:
        """按子任务 domain_tag 路由到对应插件的匹配策略执行。"""
        domain = subtask.domain_tag.value
        custom_executor = self._subtask_executors.get(domain)
        if custom_executor is not None:
            custom_executor(subtask)
            return

        from umcp_core.core.task import StandardTask, CustomTask, TaskStatus
        strategy = self.match_strategy_for(domain)
        if strategy is None:
            raise RuntimeError(f"domain {domain} 未注册匹配策略")
        if self.resource_repo is None:
            raise RuntimeError("resource_repo 未注入")

        candidates = self.resource_repo.find_available(subtask.domain_tag)
        result = strategy.execute(subtask, candidates)
        if not result.matched:
            subtask.cancel()
            return

        subtask.assign_to(result.selected_resource_id)
        subtask.start_execution()
        subtask.complete()

    def register_subtask_executor(
        self, domain: str, executor: Callable[[Task], None]
    ) -> None:
        """注册特定 domain 的子任务执行器（覆盖默认 _execute_subtask_by_domain）。"""
        self._subtask_executors[domain.lower()] = executor
```

**关键设计点**：
1. `execute_composite` 只负责启动，完成判定由事件驱动
2. 桥接函数通过 `task_id ∈ subtask_ids` 过滤，通过 `payload["cancelled"]` 区分完成/取消
3. `_execute_subtask_by_domain` 优先使用注册的自定义执行器
4. 子任务按各自 `domain_tag` 走现有匹配/支付/信任流程，零特殊处理

### 3.4 抽象基类零修改

- `Task` / `PackageTask` 抽象类不改（只新增 `CompositeTask` 子类）
- `MatchStrategy` / `PaymentSchema` / `TrustEngine` / `AccessRule` 不涉及
- `StandardTask` / `CustomTask` 不改

## 4. 插件包改动

### 4.1 零改动

三个插件包零改动：
- `ride_hailing` / `escort_driving` / `group_buying` 的 `plugin.json`、
  `__init__.py`、`register_plugin` 钩子均不需要修改
- 原因：子任务按各自 `domain_tag` 走现有插件流程，复合任务编排完全在核心库

### 4.2 不新增插件包

C 阶段只改造核心库，不创建新插件。

## 5. 测试与 demo

### 5.1 单元测试（核心库）

**新增 `tests/test_composite_task.py`**（20 个测试）：

| 测试 | 验证点 |
|------|--------|
| `test_composite_task_construction` | CompositeTask 构造成功，subtasks/dependencies 正确存储 |
| `test_composite_task_type` | task_type() 返回 "composite" |
| `test_dag_validation_no_cycle` | 无环 DAG 构造通过 |
| `test_dag_validation_cycle_detected` | 有环 DAG 抛 ValueError |
| `test_dag_validation_self_loop` | 自环依赖抛 ValueError |
| `test_dag_validation_missing_ref` | 依赖引用不存在的子任务 ID 抛 ValueError |
| `test_ready_subtasks_no_deps` | 无依赖时所有 DRAFT 子任务就绪 |
| `test_ready_subtasks_with_deps` | 依赖未完成时子任务不就绪；依赖完成后就绪 |
| `test_ready_subtasks_skip_non_draft` | 非 DRAFT 状态的子任务不返回 |
| `test_descendants_direct` | 直接下游返回正确 |
| `test_descendants_transitive` | 传递依赖（A→B→C）下游正确返回 |
| `test_descendants_no_downstream` | 叶子节点返回空列表 |
| `test_sync_to_package_fields` | subtasks 同步到 standard_sub_tasks/custom_sub_task |
| `test_on_subtask_completed_all_done` | 所有子任务 COMPLETED → 父任务 COMPLETED + emit COMPOSITE_COMPLETED |
| `test_on_subtask_cancelled_propagates` | 子任务取消 → 下游取消 + 递归传播 |
| `test_on_subtask_cancelled_no_dep_siblings_continue` | 无依赖兄弟任务不被取消 |
| `test_fail_composite_when_any_cancelled` | 存在 CANCELLED 子任务 → 父任务 CANCELLED + emit COMPOSITE_FAILED |
| `test_idempotent_complete` | 已 COMPLETED 的父任务重复触发不报错 |
| `test_idempotent_fail` | 已 CANCELLED 的父任务重复触发不报错 |
| `test_event_filter_by_composite_task_id` | 其他复合任务的子任务事件不触发本任务回调 |

### 5.2 Server 编排单元测试

**新增 `tests/test_composite_orchestration.py`**（10 个测试）：

| 测试 | 验证点 |
|------|--------|
| `test_execute_composite_publishes_parent` | execute_composite 后父任务进入 MATCHING |
| `test_execute_composite_binds_event_bus` | 父任务绑定 EventBus 并订阅子任务事件 |
| `test_dispatch_ready_subtasks_publishes_subtasks` | 就绪子任务被 publish |
| `test_execute_subtask_by_domain_uses_domain_strategy` | 子任务按 domain_tag 路由到对应 MatchStrategy |
| `test_execute_subtask_no_match_cancels` | 无匹配资源时子任务被取消 |
| `test_bridge_task_completed_to_subtask_event` | TASK_COMPLETED 事件桥接到 SUBTASK_COMPLETED |
| `test_bridge_task_cancelled_to_subtask_cancelled` | cancel() 的 TASK_COMPLETED(payload.cancelled=True) 桥接到 SUBTASK_CANCELLED |
| `test_register_subtask_executor_overrides_default` | 自定义执行器覆盖默认 _execute_subtask_by_domain |
| `test_execute_composite_rejects_non_composite` | 非 CompositeTask 抛 TypeError |
| `test_execute_composite_rejects_non_draft` | 非 DRAFT 状态抛 RuntimeError |

### 5.3 端到端测试

**新增 `tests/test_end_to_end_composite_task.py`**（8 个测试）：

| 测试 | 验证点 |
|------|--------|
| `test_parallel_composite_all_complete` | 3 个无依赖子任务（ride + escort + group_buying）并行执行 → 父任务 COMPLETED |
| `test_serial_composite_pipeline` | A→B→C 串行依赖，按序完成 → 父任务 COMPLETED |
| `test_mixed_dag_parallel_and_serial` | 混合 DAG（A∥B→C）执行顺序正确 → 父任务 COMPLETED |
| `test_failure_propagation_cancels_downstream` | A 失败 → B（依赖 A）取消，C（无依赖）继续完成 → 父任务 CANCELLED |
| `test_failure_no_dep_sibling_continues` | A 失败，B（无依赖）已完成 → 父任务 CANCELLED，但 B 保持 COMPLETED |
| `test_cross_domain_subtasks_use_domain_routing` | ride 子任务用 ride 域 MatchStrategy，group_buying 子任务用 gb 域 MatchStrategy |
| `test_custom_executor_per_domain` | 注册 ride 域自定义执行器（延迟完成），验证覆盖默认行为 |
| `test_tender_task_backward_compatible` | TenderTask（继承 PackageTask）行为零改动，现有集采流程正常 |

### 5.4 Demo

**新增 `examples/composite_task_demo.py`**：

场景：商务出行包
- 子任务 1：打车去机场（ride 域，StandardTask，无依赖）
- 子任务 2：代驾回家（escort 域，StandardTask，depends_on=[1]）
- 子任务 3：团购伴手礼（group_buying 域，StandardTask，无依赖，与打车并行）

输出：
1. 构造 CompositeTask，打印 DAG 拓扑
2. `server.execute_composite(composite)`
3. 打印执行顺序：打车 + 团购并行启动 → 打车完成触发代驾启动 → 代驾完成 → 父任务 COMPLETED
4. 演示失败传播：构造另一个 CompositeTask，打车失败 → 代驾取消 → 父任务 CANCELLED

### 5.5 不破坏现有测试

所有现有测试（267 个，含阶段四 B 的 19+5 个）应零改动通过——这是
向后兼容性的直接验证。

## 6. 兼容性与迁移

### 6.1 向后兼容保证

| 现有 API | C 阶段后行为 |
|---------|-------------|
| `PackageTask` 抽象类 | 零修改；新增 `CompositeTask` 子类不影响现有子类 |
| `TenderTask`（继承 PackageTask） | 行为零改动；不强制改为 CompositeTask |
| `EventType.TASK_COMPLETED` / `TASK_PUBLISHED` 等 | 保留；新增 `SUBTASK_*` / `COMPOSITE_*` 不影响现有订阅 |
| `EventBus.subscribe` | 零修改；桥接函数只是新增订阅者 |
| `UMCPServer.register_*` / `load_plugin` | 零修改；新增 `execute_composite` / `register_subtask_executor` |
| 现有单插件测试 | 零改动通过（不使用 CompositeTask） |

### 6.2 迁移路径

C 阶段对插件完全透明，无需迁移：
- 插件 manifest 不变
- 插件 `register_plugin` 钩子不变
- 子任务按各自 domain 走现有流程

### 6.3 已知限制（留给后续）

- 跨域资源（一个资源同时属于多个 domain）
- 子任务间数据传递（当前仅状态依赖）
- 复合任务持久化与恢复（当前仅内存态）
- 子任务超时自动取消
- 复合任务进度查询索引 API

## 7. 验收标准

- [ ] 20 个单元测试（`test_composite_task.py`）全部通过
- [ ] 10 个 Server 编排单元测试（`test_composite_orchestration.py`）全部通过
- [ ] 8 个端到端测试（`test_end_to_end_composite_task.py`）全部通过
- [ ] 现有 267 个测试零改动通过
- [ ] `examples/composite_task_demo.py` 可独立运行，输出证明 DAG 编排与失败传播
- [ ] 核心库改动文件数 = 3（`task.py`、`events/types.py`、`server.py`）
- [ ] 抽象基类（`Task` / `PackageTask` / `MatchStrategy` / `PaymentSchema` / `TrustEngine` / `AccessRule`）零修改
- [ ] 插件包零改动
- [ ] 总测试数：267 + 20 + 10 + 8 = 305 passed

## 8. 数据流

```
用户创建 CompositeTask(subtasks=[打车, 代驾, 团购], dependencies={代驾: [打车]})
  ↓
server.execute_composite(composite)
  ├─ composite.bind_event_bus → 订阅 SUBTASK_COMPLETED/CANCELLED
  ├─ 注册桥接：TASK_COMPLETED → SUBTASK_*
  ├─ composite.publish → MATCHING
  ├─ _dispatch_ready_subtasks
  │   ├─ 打车（无依赖，就绪）→ publish → InstantMatch → assign → complete
  │   │   → emit TASK_COMPLETED → 桥接 → emit SUBTASK_COMPLETED
  │   │   → _on_subtask_completed：代驾未完成，等待
  │   ├─ 代驾（依赖打车，未就绪）→ 跳过
  │   └─ 团购（无依赖，就绪）→ publish → Bidding → assign → complete
  │       → emit TASK_COMPLETED → 桥接 → emit SUBTASK_COMPLETED
  │       → _on_subtask_completed：代驾未完成，等待
  ↓
打车完成事件触发桥接回调：
  → emit SUBTASK_COMPLETED → _on_subtask_completed（代驾未完成，等待）
  → _dispatch_ready_subtasks（桥接回调中调用）→ 代驾就绪 → 派发执行
  → 代驾 complete → emit TASK_COMPLETED → 桥接 → emit SUBTASK_COMPLETED
  → _on_subtask_completed：全部终态 + 无失败 → _complete_composite
  → COMPOSITE_COMPLETED

失败传播场景（打车失败）：
  打车 cancel() → emit TASK_COMPLETED(cancelled=True) → 桥接 → SUBTASK_CANCELLED
  → _on_subtask_cancelled：
      ├─ descendants(打车) = [代驾] → 代驾 cancel() → 递归 emit SUBTASK_CANCELLED
      └─ 检查全部终态 → 存在 CANCELLED → _fail_composite → COMPOSITE_FAILED
```
