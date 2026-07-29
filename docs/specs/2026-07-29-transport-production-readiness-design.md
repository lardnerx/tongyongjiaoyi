# 阶段五 C：transport 生产就绪修复 设计规格

> **承接：** 阶段五 B（HTTP API + JWT 认证）最终审查发现的 4 个阻断级生产就绪问题。
>
> **目标：** 修复 4 个阻断项，使 transport 层在 PG 模式下可用、token 吊销完整、WS 推送链路对真实业务事件生效、应用关闭时释放资源。

---

## 背景与问题陈述

阶段五 B 在 in-memory 模式下测试 447 passed，但最终整体审查发现 4 个生产就绪阻断项：

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | logout/refresh token 吊销不完整 | logout 只吊销 access jti，refresh 仍可换新 | 登出形同虚设 |
| 2 | list 端点穿透仓储私有属性 | router 用 `getattr(repo, "_tasks", {})`，PG 仓储无此属性 | PG 模式下 list 静默返回空 |
| 3 | lifespan 未释放 PG 资源 | shutdown 不调用 `server.dispose()` | PG 连接池泄漏 |
| 4 | WS 推送链路对真实事件不生效 | Task._emit payload 缺 demander_id；Deal 完全不发事件 | WS 推送白名单中 task/deal 事件永不触发 |

---

## 设计决策

### 决策 1：Token 关联策略 — access 嵌入 refresh_jti

签发时在 access token 的 claims 里嵌入 `refresh_jti` 字段。logout 解码 access 即可拿到 refresh_jti 一并吊销，无需客户端额外传参，无需服务端维护映射。

### 决策 2：list 查询过滤策略 — 仓储返回全量 + router 过滤

仓储接口加 `list_all() -> list[T]` 返回全量领域对象，router 层按 status/domain_tag 等参数过滤。接口简单，PG 实现为 `SELECT *`，小数据量场景足够。

### 决策 3：Deal 事件范围 — Task + Deal 都修

- Task._emit payload 补 `demander_id`（始终）+ `supplier_id`（当 assigned 时）
- Deal 状态变更补发 DEAL_* 事件，复用已有 EventType 枚举

### 决策 4：Deal activate 事件映射 — 复用 DEAL_PAID

`Deal.activate()` 映射到 `DEAL_PAID`（语义为"已付款进入履约"），不新增枚举。

---

## 功能设计

### 功能 1：Token 吊销完整性

#### 1.1 JwtService.issue 改造

当前 `issue` 分别生成 access_jti 和 refresh_jti，两者无关联。改为：

1. 先生成 `refresh_jti`
2. access token payload 增加 `refresh_jti` 字段（引用同一 refresh_jti）
3. refresh token payload 保持不变（含自己的 jti）

**access token claims 变化：**
```
现有：{sub, name, roles, active_role, iat, exp, jti, type:"access"}
新增：{..., refresh_jti: "<refresh_token的jti>"}
```

#### 1.2 logout 端点改造

当前 logout 从 Authorization header 解码 access token，取 `jti` 吊销。改为：

1. 解码 access token
2. 取 `jti`（access 的 jti）→ 吊销
3. 取 `refresh_jti`（嵌入的 refresh 的 jti）→ 吊销

#### 1.3 refresh 端点改造（token 轮换）

当前 refresh 用旧 refresh token 签发新对，旧 refresh token 仍有效。改为：

1. 解码旧 refresh token，验证未吊销
2. **吊销旧 refresh_jti**（token 轮换）
3. 签发新对（新 access 含新 refresh_jti）
4. 旧 access token 的 jti 不主动吊销（自然过期），因为客户端会用新 access 替换

---

### 功能 2：list 端点仓储接口

#### 2.1 Repository 接口扩展

在 `repositories/interfaces.py` 的 3 个仓储接口各加 `list_all()` 抽象方法：

```python
# TaskRepository
def list_all(self) -> list[Task]:
    """返回所有任务（router 层负责过滤）。"""

# ResourceRepository
def list_all(self) -> list[Resource]:
    """返回所有资源（router 层负责过滤）。"""

# DealRepository
def list_all(self) -> list[Deal]:
    """返回所有交易（router 层负责过滤）。"""
```

#### 2.2 InMemory*Repository 实现

```python
# InMemoryTaskRepository
def list_all(self) -> list[Task]:
    with self._lock:
        return list(self._tasks.values())

# InMemoryResourceRepository
def list_all(self) -> list[Resource]:
    with self._lock:
        return list(self._resources.values())

# InMemoryDealRepository
def list_all(self) -> list[Deal]:
    with self._lock:
        return list(self._deals.values())
```

#### 2.3 Postgres*Repository 实现

```python
# PostgresTaskRepository
def list_all(self) -> list[Task]:
    with self._session_factory() as session:
        rows = session.query(TaskModel).all()
        return [task_converter.to_domain(r) for r in rows]

# PostgresResourceRepository
def list_all(self) -> list[Resource]:
    with self._session_factory() as session:
        rows = session.query(ResourceModel).all()
        return [resource_converter.to_domain(r) for r in rows]

# PostgresDealRepository
def list_all(self) -> list[Deal]:
    with self._session_factory() as session:
        rows = session.query(DealModel).all()
        return [deal_converter.to_domain(r) for r in rows]
```

#### 2.4 router 改造

三个 list 端点从 `getattr(repo, "_tasks", {})` 改为 `repo.list_all()`：

- `tasks.py:list_tasks`：`server.task_repo.list_all()` → 按 status/domain_tag 过滤 → 分页
- `resources.py:list_resources`：`server.resource_repo.list_all()` → 按 status/domain_tag 过滤 → 分页
- `deals.py:list_deals`：`server.deal_repo.list_all()` → 按 status 过滤 → 分页

---

### 功能 3：lifespan 资源释放

在 `transport/app.py` 的 lifespan shutdown 分支，现有逻辑之后追加：

```python
# 现有
if ws_bridge_ref["bridge"]:
    server.event_bus.unsubscribe_all(ws_bridge_ref["bridge"])
await ws_manager.disconnect_all()
# 新增
server.stop()
server.dispose()
```

`server.dispose()` 内部有 `hasattr(self, "_postgres_bundle")` 守卫，in-memory 模式下是 no-op，安全。

---

### 功能 4：WS 推送链路

#### 4.1 Task._emit payload 补全

当前 `Task._emit`（task.py:120-131）payload 模板：
```python
{"task_id": self.task_id, **(payload or {})}
```

改为：
```python
{
    "task_id": self.task_id,
    "demander_id": self.demander_id,
    **(payload or {}),
}
```

`supplier_id` 在 `assign_to` 时通过 payload 传入（assign_to 已有 supplier_id 参数）：
```python
def assign_to(self, resource: Resource) -> None:
    # 现有逻辑
    self._emit(EventType.TASK_ASSIGNED, payload={"supplier_id": resource.supplier_id})
```

#### 4.2 Deal 事件机制

为 Deal 添加与 Task 一致的事件发布机制：

**Deal 类扩展：**
```python
class Deal:
    def __init__(self, ..., event_bus: EventBus | None = None):
        # 现有字段
        self._event_bus: EventBus | None = event_bus

    def bind_event_bus(self, bus: EventBus) -> None:
        self._event_bus = bus

    def _emit(self, event_type: EventType, payload: dict[str, Any] | None = None) -> None:
        if self._event_bus is None:
            return
        event = Event(
            type=event_type,
            payload={
                "deal_id": self.deal_id,
                "task_id": self.task_id,
                "demander_id": self.demander_id,
                "supplier_id": self.supplier_id,
                **(payload or {}),
            },
        )
        self._event_bus.publish(event)
```

**Deal 状态变更发事件：**
- `activate()` → `DEAL_PAID`（复用，语义"已付款进入履约"）
- `complete()` → `DEAL_COMPLETED`
- `open_dispute()` → `DEAL_DISPUTED`

**Deal 创建时发 DEAL_CREATED：** 由 router 层在 `deal_repo.save(deal)` 后手动发布，或在 Deal 构造时发。考虑到 Deal 构造时可能未绑定 event_bus，采用 router 层发布：

```python
# deals.py create_deal
deal = Deal(...)
deal.bind_event_bus(server.event_bus)
deal.activate()  # 若创建即激活
server.deal_repo.save(deal)
```

或更简单：router 层在创建后手动 `server.event_bus.publish(Event(type=DEAL_CREATED, payload={...}))`。

**最终方案：** Deal 构造时不发事件；router 层创建 Deal 后调用 `deal.bind_event_bus(server.event_bus)`；Deal 的 `activate/complete/open_dispute` 方法内部发事件。DEAL_CREATED 由 router 层在 `deal_repo.save` 后发布（因为 Deal 构造时无 event_bus）。

#### 4.3 Deal 创建时绑定 event_bus 的位置

在 `deals.py:create_deal` 中：
```python
deal = Deal(...)
deal.bind_event_bus(server.event_bus)
server.deal_repo.save(deal)
# 发布创建事件
server.event_bus.publish(Event(
    type=EventType.DEAL_CREATED,
    payload={
        "deal_id": deal.deal_id,
        "task_id": deal.task_id,
        "demander_id": deal.demander_id,
        "supplier_id": deal.supplier_id,
    },
))
```

---

## 错误处理

- Token 吊销：logout/refresh 解码失败时返回 401（现有行为，不变）
- list_all：PG 查询失败时由全局异常处理器返回 500（现有行为，不变）
- Deal 事件发布：`_emit` 在 event_bus 为 None 时静默返回（与 Task 一致）
- lifespan：dispose 在 in-memory 模式下是 no-op

---

## 测试策略

### 单元测试

- **JwtService**：验证 access token 含 `refresh_jti` 字段
- **logout**：吊销后 access 和 refresh 都在黑名单
- **refresh**：轮换后旧 refresh 在黑名单，新对可用
- **list_all**：3 个仓储的 InMemory 和 PG 实现各验证返回全量
- **Deal._emit**：绑定 event_bus 后状态变更触发对应事件
- **Task._emit**：payload 含 demander_id

### 集成测试

- **E2E logout**：登录 → logout → 用旧 refresh token 调 refresh 应 401
- **E2E list**：创建多条记录 → list 返回全量 → 按 status 过滤
- **E2E WS 推送**：WS 连接 → 创建 task → 收到 task.published 推送（payload 含 demander_id 匹配登录用户）

### 回归

- 现有 447 passed 测试不应被破坏
- 新增测试不应引入 flaky

---

## 影响文件清单

### 修改

- `src/umcp_core/transport/auth.py` — JwtService.issue 改造
- `src/umcp_core/transport/routers/auth.py` — logout/refresh 改造
- `src/umcp_core/repositories/interfaces.py` — 3 个仓储加 list_all
- `src/umcp_core/repositories/in_memory.py` — 3 个 InMemory 仓储实现 list_all
- `src/umcp_core/repositories/postgres/task_repo.py` — 实现 list_all
- `src/umcp_core/repositories/postgres/resource_repo.py` — 实现 list_all
- `src/umcp_core/repositories/postgres/deal_repo.py` — 实现 list_all
- `src/umcp_core/transport/routers/tasks.py` — list_tasks 用 list_all
- `src/umcp_core/transport/routers/resources.py` — list_resources 用 list_all
- `src/umcp_core/transport/routers/deals.py` — list_deals 用 list_all + Deal 创建发事件
- `src/umcp_core/transport/app.py` — lifespan 加 server.stop/dispose
- `src/umcp_core/core/task.py` — _emit payload 补 demander_id + assign_to 补 supplier_id
- `src/umcp_core/core/deal.py` — 添加 event_bus 机制 + 状态变更发事件

### 测试

- `tests/test_jwt_service.py` — 补 refresh_jti 验证
- `tests/test_auth_router.py` — 补 logout 吊销 refresh、refresh 轮换
- `tests/test_repositories_in_memory.py` — 补 list_all 测试
- `tests/test_postgres_repos.py` — 补 list_all 测试（PG）
- `tests/test_http_e2e.py` — 补 logout E2E、list 过滤
- `tests/test_ws_integration.py` — 升级 fallback 测试为真实推送验证
- `tests/test_deals.py`（新建或现有）— Deal 事件发布测试

---

## 非目标（YAGNI）

- 不做 Redis 黑名单（多进程支持留待未来）
- 不做 JWT secret 长度校验（非阻断建议，留作后续）
- 不做 CORS 默认值收紧（非阻断建议，留作后续）
- 不做 WS 首帧认证（非阻断建议，留作后续）
- 不做所属权校验（非阻断建议，留作后续）
- 不做 `matches.py` 异常捕获对齐（非阻断建议，留作后续）
- 不做 `trust.py` 公开 accessor（非阻断建议，留作后续）
- 不清理 `app.py` 未使用 import（非阻断建议，留作后续）
- 不改 `asyncio.get_event_loop()` → `get_running_loop()`（非阻断建议，留作后续）
- 不抽公共测试 stub（非阻断建议，留作后续）
