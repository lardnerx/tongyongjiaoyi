# 陪驾业务核心闭环 - 切片2：预约单全流程 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现预约单端到端闭环（学员下单→Top3推荐→选教练→Mock支付定金→教练确认→签到→签退→双向评价），复用切片1的签到/签退/评价接口，新增预约单专用的选教练、支付、确认/拒绝接口与前端页面。

**架构：** 后端在 escort orders router 新增 `select-coach` 端点，新建 payments router 和 deals router 扩展；PaymentService 在插件 `register_plugin` 钩子中注册到 `server.payment_service`；预约单的签到/签退/评价复用切片1已有的 task-based 端点。前端新增 book-scheduled 页面、Mock 支付组件、教练确认/拒绝组件，扩展学员/教练订单详情页。

**技术栈：** FastAPI、Pydantic、Next.js 14、TypeScript、React Query、Zustand、Vitest

---

## 后端关键上下文

**预约单 task 生命周期（与实时单不同）：**
- `create_order`（SCHEDULED 分支）：task 保存为 `draft` 状态，返回 Top3 候选 resource_ids
- `select-coach`（新端点）：task `draft` → `publish_for_claim()` → `published` → `assign_to(resource_id)` → `assigned` + 创建 `Deal(pending)`
- 签到/签退/评价：复用切片1的 `/orders/{task_id}/check-in`、`/orders/{task_id}/check-out`、`/orders/{task_id}/reviews`

**Deal 状态机：** `pending` → `active`（教练确认）→ 终态。Reject 走 `cancel()`。签到/签退操作 task，不操作 deal（deal 仅用于支付/合约记录）。

**PaymentService（已存在，未注册到 server）：**
- `src/umcp_core/shared/payment/service.py` 的 `PaymentService` 封装网关+仓储+事件
- `MockGateway` 同步成功，`InMemoryPaymentRepository` 内存存储
- 本计划在 `register_plugin` 中创建实例并挂载到 `server.payment_service`

**定金计算：** `PaymentSchema.calculate(task, deal)` 返回 `PaymentOrder.total_amount`（= `actual_hours * hourly_rate`），定金 = `total_amount * 0.3`（30% 比例）。

**EventType（已存在）：** `DEAL_CONFIRMED`、`DEAL_REJECTED`、`PAYMENT_PAID`、`DEAL_PAID`、`DEAL_CANCELLED` 均已在 `events/types.py` 中定义。`DEAL_PAID`/`DEAL_CANCELLED`/`DEAL_CONFIRMED`/`DEAL_REJECTED` 已在 `WS_PUSHABLE_EVENTS` 中；`PAYMENT_PAID` 需新增。

**_extract_user_ids 提取规则：** 从 event.payload 提取 `demander_id`/`supplier_id`/`user_id` 作为 WS 推送目标。所以新端点发布事件时须在 payload 中包含 `supplier_id`（教练）和 `demander_id`（学员）。

**现有端点（不修改）：**
- `POST /api/v1/escort/orders`（SCHEDULED 分支已返回 candidates）
- `POST /api/v1/escort/orders/{task_id}/check-in` / `check-out`（task-based，预约单复用）
- `POST /api/v1/escort/orders/{task_id}/reviews`（双向评价）
- `GET /api/v1/deals/{deal_id}`（通用 deal 查询，前端可直接用）

**测试 fixture 模式：** 参考 `tests/test_escort_claim.py` 的 `client_and_server` fixture（带陪驾插件 + TestClient）和 `_auth_headers` 辅助函数。

---

## 文件结构

### 后端新增/修改

| 文件 | 操作 | 职责 |
|------|------|------|
| `plugins/escort_driving/__init__.py` | 修改 | 在 `register_plugin` 中创建 `PaymentService` 并挂载到 `server.payment_service` |
| `src/umcp_core/transport/ws.py` | 修改 | `WS_PUSHABLE_EVENTS` 新增 `PAYMENT_PAID` |
| `src/umcp_core/transport/routers/escort/orders.py` | 修改 | `OrderInfo` 扩展字段；新增 `select-coach` 端点 |
| `src/umcp_core/transport/routers/escort/payments.py` | 创建 | Mock 支付端点 + 支付状态查询 |
| `src/umcp_core/transport/routers/escort/deals.py` | 创建 | 教练确认/拒绝预约单端点 |
| `src/umcp_core/transport/routers/escort/__init__.py` | 修改 | 注册 payments_router 和 deals_router |
| `tests/test_escort_select_coach.py` | 创建 | select-coach 端点测试 |
| `tests/test_escort_payments.py` | 创建 | Mock 支付端点测试 |
| `tests/test_escort_deals_confirm.py` | 创建 | 确认/拒绝端点测试 |
| `tests/test_escort_scheduled_e2e.py` | 创建 | 预约单全流程集成测试 |

### 前端新增/修改

| 文件 | 操作 | 职责 |
|------|------|------|
| `web/src/types/escort.ts` | 修改 | 新增 `DealInfo`、`PaymentInfo`、`ScheduledOrderResponse` 类型 |
| `web/src/hooks/use-scheduled.ts` | 创建 | 预约单相关 hooks（selectCoach、mockPay、confirmDeal、rejectDeal、useDeal、usePayment） |
| `web/src/app/(protected)/escort/student/book-scheduled/page.tsx` | 创建 | 预约单下单页（时间+地点+等级偏好→Top3候选） |
| `web/src/components/mock-payment.tsx` | 创建 | Mock 支付组件（显示定金金额+支付按钮） |
| `web/src/app/(protected)/escort/student/orders/[id]/page.tsx` | 修改 | 学员订单详情：预约单分支（选教练→支付→等待确认→签到签退→评价） |
| `web/src/app/(protected)/escort/coach/orders/[id]/page.tsx` | 修改 | 教练订单详情：预约单分支（确认/拒绝按钮） |
| `web/src/app/(protected)/dashboard/page.tsx` | 修改 | 学员入口新增"预约叫车"按钮 |
| `web/src/lib/order-realtime-store.ts` | 修改 | 新增 dealStatusUpdates 状态（WS deal 事件→deal 状态） |
| `web/tests/scheduled-flow.test.ts` | 创建 | 预约单前端逻辑测试 |

---

## 任务 1：注册 PaymentService 到 server

**文件：**
- 修改：`plugins/escort_driving/__init__.py`
- 测试：`tests/test_escort_plugin_registration.py`（已有，扩展）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_escort_plugin_registration.py` 末尾追加：

```python
def test_payment_service_registered(server_with_escort):
    """register_plugin 应将 PaymentService 挂载到 server.payment_service。"""
    from umcp_core.shared.payment.service import PaymentService
    assert hasattr(server_with_escort, "payment_service")
    assert isinstance(server_with_escort.payment_service, PaymentService)


def test_payment_service_uses_event_bus(server_with_escort):
    """PaymentService 应共享 server.event_bus，事件能被订阅者收到。"""
    received = []
    server_with_escort.event_bus.subscribe_all(lambda e: received.append(e))

    from umcp_core.shared.payment.base import PaymentType
    server_with_escort.payment_service.create_payment(
        deal_id="deal_test", user_id="u1", amount=48.0, payment_type=PaymentType.DEPOSIT
    )
    server_with_escort.payment_service.confirm_payment(
        payment_id=server_with_escort.payment_service.repo.find_by_deal("deal_test")[0]["payment_id"]
    )

    types = [e.type.value for e in received]
    assert "payment.paid" in types
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_plugin_registration.py::test_payment_service_registered tests/test_escort_plugin_registration.py::test_payment_service_uses_event_bus -v`
预期：FAIL，报错 `AttributeError: 'UMCPServer' object has no attribute 'payment_service'`

- [ ] **步骤 3：修改 register_plugin 注册 PaymentService**

在 `plugins/escort_driving/__init__.py` 的 `register_plugin` 函数末尾追加：

```python
    # 注册支付服务（MockGateway + 内存仓储，挂载到 server.payment_service）
    from umcp_core.shared.payment.mock import MockGateway
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    from umcp_core.shared.payment.service import PaymentService

    server.payment_service = PaymentService(
        gateway=MockGateway(),
        repo=InMemoryPaymentRepository(),
        event_bus=server.event_bus,
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_plugin_registration.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add plugins/escort_driving/__init__.py tests/test_escort_plugin_registration.py
git commit -m "feat(escort): register PaymentService on server in plugin hook"
```

---

## 任务 2：PAYMENT_PAID 加入 WS 推送白名单

**文件：**
- 修改：`src/umcp_core/transport/ws.py:21-46`
- 测试：`tests/test_ws_integration.py`（已有，扩展）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_ws_integration.py` 末尾追加：

```python
def test_payment_paid_is_pushable():
    """PAYMENT_PAID 应在 WS_PUSHABLE_EVENTS 中。"""
    from umcp_core.transport.ws import WS_PUSHABLE_EVENTS
    from umcp_core.events.types import EventType
    assert EventType.PAYMENT_PAID in WS_PUSHABLE_EVENTS
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_ws_integration.py::test_payment_paid_is_pushable -v`
预期：FAIL，`AssertionError`

- [ ] **步骤 3：将 PAYMENT_PAID 加入 WS_PUSHABLE_EVENTS**

在 `src/umcp_core/transport/ws.py` 的 `WS_PUSHABLE_EVENTS` 集合中，在 `EventType.DEAL_CONFIRMED` 之前添加一行：

```python
    EventType.PAYMENT_PAID,
```

修改后的集合尾部应为：
```python
    EventType.DEAL_CANCELLED,
    EventType.DEAL_RESOLVED,
    EventType.DEAL_CONFIRMED,
    EventType.DEAL_REJECTED,
    EventType.PAYMENT_PAID,
    EventType.SUBTASK_COMPLETED,
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_ws_integration.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/ws.py tests/test_ws_integration.py
git commit -m "feat(ws): add PAYMENT_PAID to WS pushable events"
```

---

## 任务 3：扩展 OrderInfo + select-coach 端点

**文件：**
- 修改：`src/umcp_core/transport/routers/escort/orders.py`
- 测试：`tests/test_escort_select_coach.py`（创建）

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_escort_select_coach.py`：

```python
"""预约单 select-coach 端点测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    """带陪驾插件 + 教练资源的 FastAPI 应用。"""
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    from plugins.escort_driving import register_plugin

    class _Coach(Resource):
        def __init__(self, rid, level="B"):
            super().__init__(
                supplier_id=rid,
                domain_tag=DomainTag.of("escort"),
                resource_id=rid,
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "manual"
            self.metadata["coach_level"] = level

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach("coach_1", "B"))
    server.resource_repo.save(_Coach("coach_2", "A"))
    server.resource_repo.save(_Coach("coach_3", "B"))
    config = TransportConfig(jwt_secret="test-secret")
    return TestClient(create_app(server, config)), server


def _auth_headers(server, user_id="u1", roles=None):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    if roles and "supplier" in roles:
        user.add_role(_ClaimsSupplier())
    if roles:
        user.switch_role(roles[0])
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_scheduled_order(client, server, demander_id="u1"):
    """创建预约单，返回 (task_id, candidates)。"""
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": demander_id,
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
            "coach_level_pref": "ANY",
        },
        headers=_auth_headers(server, demander_id),
    )
    data = resp.json()["data"]
    return data["task_id"], data["candidates"]


def test_select_coach_creates_deal(client_and_server):
    """学员选教练后创建 Deal(pending)，task 状态变为 assigned。"""
    client, server = client_and_server
    task_id, candidates = _create_scheduled_order(client, server)
    assert len(candidates) > 0

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deal_id"]
    assert data["status"] == "pending"
    assert data["deposit_amount"] > 0

    # task 状态应为 assigned
    task_resp = client.get(
        f"/api/v1/escort/orders/{task_id}",
        headers=_auth_headers(server),
    )
    assert task_resp.json()["data"]["status"] == "assigned"
    assert task_resp.json()["data"]["deal_id"] == data["deal_id"]


def test_select_coach_wrong_task_state_fails(client_and_server):
    """task 非 draft 状态时选教练失败（409）。"""
    client, server = client_and_server
    task_id, candidates = _create_scheduled_order(client, server)
    # 先选一次
    client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth_headers(server),
    )
    # 再选应失败（task 已 assigned）
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[1] if len(candidates) > 1 else candidates[0]},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 409


def test_select_non_candidate_fails(client_and_server):
    """选择不在候选列表中的教练失败（403）。"""
    client, server = client_and_server
    task_id, candidates = _create_scheduled_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": "non_existent_coach"},
        headers=_auth_headers(server),
    )
    assert resp.status_code in (403, 404)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_select_coach.py -v`
预期：FAIL，报错 `AttributeError` 或 404（端点不存在）

- [ ] **步骤 3：扩展 OrderInfo 并实现 select-coach 端点**

在 `src/umcp_core/transport/routers/escort/orders.py` 中：

3a. 扩展 `OrderInfo` 类，新增 `scheduled_at`、`coach_level_pref`、`deal_id` 字段：

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
```

3b. 修改 `_task_to_order_info` 函数提取新字段：

```python
def _task_to_order_info(task: EscortTask) -> OrderInfo:
    return OrderInfo(
        task_id=task.task_id,
        order_type=task.order_type,
        status=task.status,
        demander_id=task.demander_id,
        car_type=task.structured_fields.get("car_type", ""),
        duration_hours=task.structured_fields.get("duration_hours", 0),
        assigned_resource_id=task.assigned_resource_id,
        title=task.title,
        scheduled_at=task.structured_fields.get("scheduled_at"),
        coach_level_pref=task.structured_fields.get("coach_level_pref"),
        deal_id=None,  # 由调用方按需填充（get_order 反查 deal_repo）
    )
```

注意：`deal_id` 在 `_task_to_order_info` 中默认为 `None`，由 `get_order` 端点在返回前通过 `server.deal_repo.find_by_task(task_id)` 反查填充。

3c. 修改 `get_order` 端点，反查 deal_id 填充到 OrderInfo：

```python
@router.get("/orders/{task_id}", response_model=Envelope)
async def get_order(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查询单个订单详情。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    info = _task_to_order_info(task)
    # 预约单反查 deal_id
    if task.order_type == "SCHEDULED":
        deals = server.deal_repo.find_by_task(task_id)
        if deals:
            info.deal_id = deals[-1].deal_id  # 取最新 deal
    return ok(info.model_dump())
```

3d. 在文件末尾（`check_out_order` 之后）新增 `select-coach` 端点：

```python
class SelectCoachRequest(BaseModel):
    resource_id: str


class SelectCoachResponse(BaseModel):
    deal_id: str
    task_id: str
    resource_id: str
    status: str
    deposit_amount: float


@router.post("/orders/{task_id}/select-coach", response_model=Envelope)
async def select_coach(
    task_id: str,
    req: SelectCoachRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """预约单：学员选择教练，创建 Deal(pending)。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    if task.order_type != "SCHEDULED":
        raise IllegalStateError(message="仅预约单支持选教练")
    if task.status != TaskStatus.DRAFT:
        raise IllegalStateError(message=f"订单状态 {task.status} 不允许选教练")

    # 校验 resource_id 在候选列表中（重新匹配验证）
    strategy = server.scheduled_match_strategy_for(task.domain_tag.value)
    if strategy is not None:
        candidates = server.resource_repo.list_all()
        domain_candidates = [r for r in candidates if r.domain_tag.value == task.domain_tag.value]
        result = strategy.execute(task, domain_candidates)
        if req.resource_id not in result.candidates:
            raise PermissionDeniedError(message="所选教练不在候选列表中")

    resource = server.resource_repo.find_by_id(req.resource_id)
    if resource is None:
        raise NotFoundError(message=f"教练 {req.resource_id} 不存在")

    # task: draft → published → assigned
    task.bind_event_bus(server.event_bus)
    try:
        task.publish_for_claim()
        task.assign_to(req.resource_id)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 计算定金：用 PaymentSchema 算总价，再取 30%
    from umcp_core.core.deal import Deal
    deal = Deal(
        task_id=task.task_id,
        resource_id=req.resource_id,
        demander_id=task.demander_id,
        supplier_id=resource.supplier_id,
    )
    deal.bind_event_bus(server.event_bus)

    schema = server.payment_schema_for(task.domain_tag.value)
    if schema is not None:
        payment_order = schema.calculate(task, deal)
        deposit_amount = round(payment_order.total_amount * 0.3, 2)
        deal.final_amount = payment_order.total_amount
    else:
        deposit_amount = 0.0

    server.deal_repo.save(deal)

    # 发布 DEAL_CREATED 事件（payload 含 supplier_id 供 WS 推送给教练）
    server.event_bus.publish(
        Event(
            type=EventType.DEAL_CREATED,
            source_layer="ESCORT",
            payload={
                "deal_id": deal.deal_id,
                "task_id": deal.task_id,
                "demander_id": deal.demander_id,
                "supplier_id": deal.supplier_id,
                "deposit_amount": deposit_amount,
            },
        )
    )

    return ok(
        SelectCoachResponse(
            deal_id=deal.deal_id,
            task_id=task.task_id,
            resource_id=req.resource_id,
            status=deal.status,
            deposit_amount=deposit_amount,
        ).model_dump()
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_select_coach.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/routers/escort/orders.py tests/test_escort_select_coach.py
git commit -m "feat(escort): add select-coach endpoint for scheduled orders"
```

---

## 任务 4：Mock 支付端点 + 支付状态查询

**文件：**
- 创建：`src/umcp_core/transport/routers/escort/payments.py`
- 修改：`src/umcp_core/transport/routers/escort/__init__.py`
- 测试：`tests/test_escort_payments.py`（创建）

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_escort_payments.py`：

```python
"""Mock 支付端点测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from plugins.escort_driving import register_plugin

    class _Coach(Resource):
        def __init__(self):
            super().__init__(
                supplier_id="coach_1",
                domain_tag=DomainTag.of("escort"),
                resource_id="coach_1",
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "manual"
            self.metadata["coach_level"] = "B"

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach())
    config = TransportConfig(jwt_secret="test-secret")
    return TestClient(create_app(server, config)), server


def _auth_headers(server, user_id="u1"):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _setup_scheduled_deal(client, server):
    """创建预约单 + 选教练，返回 (task_id, deal_id, deposit_amount)。"""
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": [],
            "duration_hours": 2,
            "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=_auth_headers(server),
    )
    task_id = resp.json()["data"]["task_id"]
    candidates = resp.json()["data"]["candidates"]

    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth_headers(server),
    )
    data = resp2.json()["data"]
    return task_id, data["deal_id"], data["deposit_amount"]


def test_mock_pay_success(client_and_server):
    """Mock 支付定金成功，支付状态变为 paid。"""
    client, server = client_and_server
    task_id, deal_id, deposit = _setup_scheduled_deal(client, server)

    resp = client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "paid"
    assert data["amount"] == deposit
    assert data["payment_id"]


def test_query_payment_by_deal(client_and_server):
    """按 deal_id 查询支付状态。"""
    client, server = client_and_server
    task_id, deal_id, _ = _setup_scheduled_deal(client, server)
    client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    resp = client.get(
        f"/api/v1/escort/payments/{deal_id}",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "paid"
    assert data["deal_id"] == deal_id


def test_mock_pay_nonexistent_deal_fails(client_and_server):
    """支付不存在的 deal 返回 404。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": "nonexistent", "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 404
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_payments.py -v`
预期：FAIL，404（端点不存在）

- [ ] **步骤 3：创建 payments router**

创建 `src/umcp_core/transport/routers/escort/payments.py`：

```python
"""陪驾 Mock 支付 router。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/escort/payments", tags=["escort-payments"])


class MockPayRequest(BaseModel):
    deal_id: str
    payment_type: str = "deposit"  # deposit | balance | full


class PaymentInfo(BaseModel):
    payment_id: str
    deal_id: str
    user_id: str
    amount: float
    payment_type: str
    status: str
    trade_no: str | None = None


@router.post("/mock-pay", response_model=Envelope)
async def mock_pay(
    req: MockPayRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """Mock 支付：创建支付意图 + 同步确认成功。"""
    deal = server.deal_repo.find_by_id(req.deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {req.deal_id} 不存在")

    payment_service = getattr(server, "payment_service", None)
    if payment_service is None:
        raise IllegalStateError(message="支付服务未注册")

    # 计算支付金额（定金 = total * 0.3）
    amount = round((deal.final_amount or 0.0) * 0.3, 2)
    if amount <= 0:
        raise IllegalStateError(message="支付金额必须大于 0")

    payment_type = PaymentType(req.payment_type)
    intent = payment_service.create_payment(
        deal_id=req.deal_id,
        user_id=current_user.user_id,
        amount=amount,
        payment_type=payment_type,
    )
    # Mock 网关同步成功，直接确认
    payment_service.confirm_payment(payment_id=intent.payment_id)

    # 手动发布 PAYMENT_PAID 事件（payload 含 supplier_id 供 WS 推送给教练）
    # 技术债说明：confirm_payment() 内部已发一次 PAYMENT_PAID，但 payload 缺
    # demander_id/supplier_id，WS _extract_user_ids 提取不到推送目标，不会推送。
    # 此处补发一次完整 payload 的事件以驱动 WS 推送。两次发布功能上不冲突
    # （第一次不被推送），后续可改造 PaymentService 让 confirm_payment 从 repo
    # 取完整字段，消除重复发布。
    server.event_bus.publish(
        Event(
            type=EventType.PAYMENT_PAID,
            source_layer="ESCORT",
            payload={
                "payment_id": intent.payment_id,
                "deal_id": req.deal_id,
                "user_id": current_user.user_id,
                "demander_id": deal.demander_id,
                "supplier_id": deal.supplier_id,
                "amount": amount,
            },
        )
    )

    persisted = payment_service.repo.find_by_id(intent.payment_id)
    return ok(
        PaymentInfo(
            payment_id=intent.payment_id,
            deal_id=req.deal_id,
            user_id=current_user.user_id,
            amount=amount,
            payment_type=req.payment_type,
            status=persisted["status"] if persisted else "paid",
            trade_no=persisted.get("trade_no") if persisted else None,
        ).model_dump()
    )


@router.get("/{deal_id}", response_model=Envelope)
async def get_payment_by_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """按 deal_id 查询支付状态（返回最新一条）。"""
    payment_service = getattr(server, "payment_service", None)
    if payment_service is None:
        raise IllegalStateError(message="支付服务未注册")
    records = payment_service.repo.find_by_deal(deal_id)
    if not records:
        raise NotFoundError(message=f"交易 {deal_id} 无支付记录")
    latest = records[-1]
    return ok(
        PaymentInfo(
            payment_id=latest["payment_id"],
            deal_id=latest["deal_id"],
            user_id=latest["user_id"],
            amount=latest["amount"],
            payment_type=latest["type"],
            status=latest["status"],
            trade_no=latest.get("trade_no"),
        ).model_dump()
    )
```

- [ ] **步骤 4：注册 payments router**

> **重要：避免命名冲突。** `src/umcp_core/transport/routers/__init__.py` 已从通用 `routers.deals` 导入 `deals_router`（前缀 `/api/v1/deals`）。escort 包下的 deals/payments router 必须使用别名 `escort_deals_router` / `escort_payments_router`，否则会覆盖通用 deals_router 导致 `/api/v1/deals/{deal_id}` 端点丢失。

修改 `src/umcp_core/transport/routers/escort/__init__.py`：

```python
"""陪驾业务 router 分区。"""

from umcp_core.transport.routers.escort.coaches import router as coaches_router
from umcp_core.transport.routers.escort.deals import router as escort_deals_router
from umcp_core.transport.routers.escort.orders import router as orders_router
from umcp_core.transport.routers.escort.payments import router as escort_payments_router
from umcp_core.transport.routers.escort.reviews import router as reviews_router

__all__ = [
    "coaches_router",
    "escort_deals_router",
    "orders_router",
    "escort_payments_router",
    "reviews_router",
]
```

同时修改 `src/umcp_core/transport/routers/__init__.py` 的 import 和 `register_routers`：

在 import 行追加（注意用别名，不要与通用 `deals_router` 冲突）：
```python
from umcp_core.transport.routers.escort import coaches_router, escort_deals_router, orders_router, escort_payments_router, reviews_router
```

在 `register_routers` 函数的陪驾区块追加：
```python
    app.include_router(escort_deals_router)
    app.include_router(escort_payments_router)
```

- [ ] **步骤 5：运行测试验证通过**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_payments.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/routers/escort/payments.py src/umcp_core/transport/routers/escort/__init__.py src/umcp_core/transport/routers/__init__.py tests/test_escort_payments.py
git commit -m "feat(escort): add mock-pay endpoint and payment status query"
```

---

## 任务 5：教练确认/拒绝预约单端点

**文件：**
- 创建：`src/umcp_core/transport/routers/escort/deals.py`
- 测试：`tests/test_escort_deals_confirm.py`（创建）

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_escort_deals_confirm.py`：

```python
"""教练确认/拒绝预约单端点测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from plugins.escort_driving import register_plugin

    class _Coach(Resource):
        def __init__(self):
            super().__init__(
                supplier_id="coach_1",
                domain_tag=DomainTag.of("escort"),
                resource_id="coach_1",
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "manual"
            self.metadata["coach_level"] = "B"

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach())
    config = TransportConfig(jwt_secret="test-secret")
    return TestClient(create_app(server, config)), server


def _auth_headers(server, user_id="u1", roles=None):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    if roles and "supplier" in roles:
        user.add_role(_ClaimsSupplier())
    if roles:
        user.switch_role(roles[0])
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _setup_paid_deal(client, server):
    """创建预约单→选教练→Mock支付，返回 (task_id, deal_id)。"""
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9, "origin_lng": 116.4,
            "car_type": "manual", "required_skills": [],
            "duration_hours": 2, "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=_auth_headers(server),
    )
    task_id = resp.json()["data"]["task_id"]
    candidates = resp.json()["data"]["candidates"]
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth_headers(server),
    )
    deal_id = resp2.json()["data"]["deal_id"]
    client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth_headers(server),
    )
    return task_id, deal_id


def test_coach_confirm_deal(client_and_server):
    """教练确认预约单：deal pending → active。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)

    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


def test_coach_reject_deal(client_and_server):
    """教练拒绝预约单：deal pending → cancelled + 退款。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)

    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/reject",
        json={"coach_id": "coach_1", "reason": "时间冲突"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


def test_confirm_wrong_coach_fails(client_and_server):
    """非该订单教练确认失败（403）。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)

    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_other"},
        headers=_auth_headers(server, "coach_other", roles=["supplier"]),
    )
    assert resp.status_code == 403


def test_confirm_already_active_fails(client_and_server):
    """已确认的 deal 再次确认失败（409）。"""
    client, server = client_and_server
    task_id, deal_id = _setup_paid_deal(client, server)
    client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 409
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_deals_confirm.py -v`
预期：FAIL，404（端点不存在）

- [ ] **步骤 3：创建 deals router**

创建 `src/umcp_core/transport/routers/escort/deals.py`：

```python
"""陪驾预约单教练确认/拒绝 router。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError, PermissionDeniedError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/escort/deals", tags=["escort-deals"])


class ConfirmRequest(BaseModel):
    coach_id: str


class RejectRequest(BaseModel):
    coach_id: str
    reason: str = ""


class DealStatusInfo(BaseModel):
    deal_id: str
    status: str
    task_id: str


@router.post("/{deal_id}/confirm", response_model=Envelope)
async def confirm_deal(
    deal_id: str,
    req: ConfirmRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练确认预约单：deal pending → active。"""
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能确认自己的订单")

    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    if deal.supplier_id != req.coach_id:
        raise PermissionDeniedError(message="只有该订单的教练才能确认")

    deal.bind_event_bus(server.event_bus)
    try:
        deal.activate()  # pending → active，发 DEAL_PAID 事件
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)

    return ok(
        DealStatusInfo(
            deal_id=deal.deal_id,
            status=deal.status,
            task_id=deal.task_id,
        ).model_dump()
    )


@router.post("/{deal_id}/reject", response_model=Envelope)
async def reject_deal(
    deal_id: str,
    req: RejectRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练拒绝预约单：deal pending → cancelled + 退款。"""
    if current_user.user_id != req.coach_id:
        raise PermissionDeniedError(message="只能拒绝自己的订单")

    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    if deal.supplier_id != req.coach_id:
        raise PermissionDeniedError(message="只有该订单的教练才能拒绝")

    deal.bind_event_bus(server.event_bus)
    try:
        deal.cancel()  # pending → cancelled，发 DEAL_CANCELLED 事件
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)

    # 退款（如果已有支付记录）
    payment_service = getattr(server, "payment_service", None)
    if payment_service is not None:
        records = payment_service.repo.find_by_deal(deal_id)
        for record in records:
            if record["status"] == "paid":
                payment_service.refund(
                    payment_id=record["payment_id"],
                    amount=record["amount"],
                    reason=req.reason or "教练拒绝预约单",
                )

    # 同步取消 task
    task = server.task_repo.find_by_id(deal.task_id)
    if task is not None and task.status != "cancelled":
        try:
            task.cancel()
            server.task_repo.save(task)
        except (RuntimeError, ValueError):
            pass  # task 可能已终态，忽略

    return ok(
        DealStatusInfo(
            deal_id=deal.deal_id,
            status=deal.status,
            task_id=deal.task_id,
        ).model_dump()
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_deals_confirm.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/routers/escort/deals.py tests/test_escort_deals_confirm.py
git commit -m "feat(escort): add deal confirm/reject endpoints for coach"
```

---

## 任务 6：预约单全流程后端集成测试

**文件：**
- 测试：`tests/test_escort_scheduled_e2e.py`（创建）

- [ ] **步骤 1：编写集成测试**

创建 `tests/test_escort_scheduled_e2e.py`：

```python
"""预约单全流程集成测试：下单→选教练→支付→确认→签到→签退→评价。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_server():
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig
    from plugins.escort_driving import register_plugin

    class _Coach(Resource):
        def __init__(self, rid="coach_1"):
            super().__init__(
                supplier_id=rid,
                domain_tag=DomainTag.of("escort"),
                resource_id=rid,
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "manual"
            self.metadata["coach_level"] = "B"

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach("coach_1"))
    config = TransportConfig(jwt_secret="test-secret")
    return TestClient(create_app(server, config)), server


def _auth(server, user_id="u1", roles=None):
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    if roles and "supplier" in roles:
        user.add_role(_ClaimsSupplier())
    if roles:
        user.switch_role(roles[0])
    return {"Authorization": f"Bearer {jwt.issue(user)['access_token']}"}


def test_scheduled_full_flow(client_and_server):
    """预约单全流程：下单→选教练→支付→确认→签到→签退→双向评价。"""
    client, server = client_and_server

    # 1. 学员创建预约单
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1", "domain_tag": "escort",
            "origin_lat": 39.9, "origin_lng": 116.4,
            "car_type": "manual", "required_skills": [],
            "duration_hours": 2, "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=_auth(server),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]
    candidates = resp.json()["data"]["candidates"]
    assert len(candidates) > 0

    # 2. 学员选教练
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth(server),
    )
    assert resp.status_code == 200
    deal_id = resp.json()["data"]["deal_id"]
    deposit = resp.json()["data"]["deposit_amount"]
    assert deposit > 0

    # 3. 学员 Mock 支付定金
    resp = client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth(server),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "paid"

    # 4. 教练确认
    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/confirm",
        json={"coach_id": candidates[0]},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"

    # 5. 教练签到（复用 task-based check-in）
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": candidates[0], "lat": 39.9, "lng": 116.4},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "in_progress"

    # 6. 教练签退
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": candidates[0], "lat": 39.9, "lng": 116.4},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"

    # 7. 学员评教练
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "很好",
        },
        headers=_auth(server),
    )
    assert resp.status_code == 200

    # 8. 教练评学员
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": candidates[0],
            "reviewer_role": "COACH",
            "ratings": {"punctuality_score": 5, "cooperation_score": 4, "payment_score": 5},
            "comment": "不错",
        },
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200

    # 9. 验证评价记录
    resp = client.get(
        f"/api/v1/escort/orders/{task_id}/reviews",
        headers=_auth(server),
    )
    assert resp.status_code == 200
    reviews = resp.json()["data"]
    assert len(reviews) == 2


def test_scheduled_reject_flow(client_and_server):
    """教练拒绝预约单：deal cancelled + task cancelled。"""
    client, server = client_and_server

    # 下单 → 选教练 → 支付
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1", "domain_tag": "escort",
            "origin_lat": 39.9, "origin_lng": 116.4,
            "car_type": "manual", "required_skills": [],
            "duration_hours": 2, "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=_auth(server),
    )
    task_id = resp.json()["data"]["task_id"]
    candidates = resp.json()["data"]["candidates"]

    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=_auth(server),
    )
    deal_id = resp.json()["data"]["deal_id"]

    client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=_auth(server),
    )

    # 教练拒绝
    resp = client.post(
        f"/api/v1/escort/deals/{deal_id}/reject",
        json={"coach_id": candidates[0], "reason": "时间冲突"},
        headers=_auth(server, candidates[0], roles=["supplier"]),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"

    # task 也应被取消
    resp = client.get(
        f"/api/v1/escort/orders/{task_id}",
        headers=_auth(server),
    )
    assert resp.json()["data"]["status"] == "cancelled"
```

- [ ] **步骤 2：运行测试验证通过**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_scheduled_e2e.py -v`
预期：PASS

- [ ] **步骤 3：运行全部陪驾测试确保无回归**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/test_escort_*.py tests/test_scheduled_match.py -v`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add tests/test_escort_scheduled_e2e.py
git commit -m "test(escort): add scheduled order end-to-end integration tests"
```

---

## 任务 7：前端类型定义 + API hooks

**文件：**
- 修改：`web/src/types/escort.ts`
- 创建：`web/src/hooks/use-scheduled.ts`

- [ ] **步骤 1：扩展类型定义**

在 `web/src/types/escort.ts` 末尾追加：

```typescript
/** 预约单下单响应（含 Top3 候选教练）。 */
export interface ScheduledOrderResponse {
  task_id: string;
  order_type: string;
  candidates: string[];
}

/** 选教练响应。 */
export interface SelectCoachResponse {
  deal_id: string;
  task_id: string;
  resource_id: string;
  status: string;
  deposit_amount: number;
}

/** 交易信息。 */
export interface DealInfo {
  deal_id: string;
  task_id: string;
  resource_id: string;
  demander_id: string;
  supplier_id: string;
  status: string;
  final_amount: number | null;
}

/** 支付信息。 */
export interface PaymentInfo {
  payment_id: string;
  deal_id: string;
  user_id: string;
  amount: number;
  payment_type: string;
  status: string;
  trade_no: string | null;
}

/** 教练确认/拒绝响应。 */
export interface DealStatusInfo {
  deal_id: string;
  status: string;
  task_id: string;
}
```

同时扩展 `OrderInfo` 接口，在 `title` 字段后追加：

```typescript
  scheduled_at?: string | null;
  coach_level_pref?: string | null;
  deal_id?: string | null;
```

- [ ] **步骤 2：创建预约单 hooks**

创建 `web/src/hooks/use-scheduled.ts`：

```typescript
"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type {
  ScheduledOrderResponse,
  SelectCoachResponse,
  DealInfo,
  PaymentInfo,
  DealStatusInfo,
} from "@/types/escort";

/** 创建预约单。 */
export function useCreateScheduledOrder() {
  return useMutation({
    mutationFn: (params: {
      demander_id: string;
      origin_lat: number;
      origin_lng: number;
      car_type: string;
      duration_hours: number;
      scheduled_at: string;
      coach_level_pref: string;
    }) =>
      apiClient.post<ScheduledOrderResponse>("/escort/orders", {
        demander_id: params.demander_id,
        domain_tag: "escort",
        origin_lat: params.origin_lat,
        origin_lng: params.origin_lng,
        car_type: params.car_type,
        required_skills: ["coach_license"],
        duration_hours: params.duration_hours,
        order_type: "SCHEDULED",
        scheduled_at: params.scheduled_at,
        coach_level_pref: params.coach_level_pref,
      }),
  });
}

/** 学员选教练。 */
export function useSelectCoach() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { taskId: string; resourceId: string }) =>
      apiClient.post<SelectCoachResponse>(
        `/escort/orders/${params.taskId}/select-coach`,
        { resource_id: params.resourceId }
      ),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: ["order", variables.taskId] });
    },
  });
}

/** Mock 支付定金。 */
export function useMockPay() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { dealId: string; paymentType?: string }) =>
      apiClient.post<PaymentInfo>("/escort/payments/mock-pay", {
        deal_id: params.dealId,
        payment_type: params.paymentType || "deposit",
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["payment", data.deal_id] });
      qc.invalidateQueries({ queryKey: ["deal", data.deal_id] });
    },
  });
}

/** 教练确认预约单。 */
export function useConfirmDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { dealId: string; coachId: string }) =>
      apiClient.post<DealStatusInfo>(
        `/escort/deals/${params.dealId}/confirm`,
        { coach_id: params.coachId }
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["deal", data.deal_id] });
      qc.invalidateQueries({ queryKey: ["order", data.task_id] });
    },
  });
}

/** 教练拒绝预约单。 */
export function useRejectDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { dealId: string; coachId: string; reason?: string }) =>
      apiClient.post<DealStatusInfo>(
        `/escort/deals/${params.dealId}/reject`,
        { coach_id: params.coachId, reason: params.reason || "" }
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["deal", data.deal_id] });
      qc.invalidateQueries({ queryKey: ["order", data.task_id] });
    },
  });
}

/** 查询 deal 信息。 */
export function useDeal(dealId: string | undefined) {
  return useQuery({
    queryKey: ["deal", dealId],
    queryFn: () => apiClient.get<DealInfo>(`/deals/${dealId}`),
    enabled: !!dealId,
  });
}

/** 查询支付状态。 */
export function usePayment(dealId: string | undefined) {
  return useQuery({
    queryKey: ["payment", dealId],
    queryFn: () => apiClient.get<PaymentInfo>(`/escort/payments/${dealId}`),
    enabled: !!dealId,
    retry: false,
  });
}
```

- [ ] **步骤 3：验证 TypeScript 编译**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx tsc --noEmit`
预期：无错误

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/types/escort.ts web/src/hooks/use-scheduled.ts
git commit -m "feat(web): add scheduled order types and API hooks"
```

---

## 任务 8：预约单下单页面（book-scheduled）

**文件：**
- 创建：`web/src/app/(protected)/escort/student/book-scheduled/page.tsx`

- [ ] **步骤 1：创建预约单下单页**

创建 `web/src/app/(protected)/escort/student/book-scheduled/page.tsx`：

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AmapPicker } from "@/components/amap-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { useCreateScheduledOrder, useSelectCoach } from "@/hooks/use-scheduled";
import type { ScheduledOrderResponse, SelectCoachResponse } from "@/types/escort";

export default function BookScheduledPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const createOrder = useCreateScheduledOrder();
  const selectCoach = useSelectCoach();

  const [location, setLocation] = useState<{ lat: number; lng: number; address: string } | null>(null);
  const [carType, setCarType] = useState("manual");
  const [duration, setDuration] = useState(2);
  const [scheduledAt, setScheduledAt] = useState("");
  const [coachLevelPref, setCoachLevelPref] = useState("ANY");
  const [scheduledResp, setScheduledResp] = useState<ScheduledOrderResponse | null>(null);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!location || !scheduledAt) {
      setError("请选择上车地点和预约时间");
      return;
    }
    setError("");
    createOrder.mutate(
      {
        demander_id: user?.user_id || "",
        origin_lat: location.lat,
        origin_lng: location.lng,
        car_type: carType,
        duration_hours: duration,
        scheduled_at: scheduledAt,
        coach_level_pref: coachLevelPref,
      },
      {
        onSuccess: (data) => setScheduledResp(data),
        onError: (e: any) => setError(e.message || "下单失败"),
      }
    );
  };

  const handleSelectCoach = async (resourceId: string) => {
    if (!scheduledResp) return;
    selectCoach.mutate(
      { taskId: scheduledResp.task_id, resourceId },
      {
        onSuccess: (data: SelectCoachResponse) => {
          router.push(`/escort/student/orders/${data.task_id}`);
        },
        onError: (e: any) => setError(e.message || "选教练失败"),
      }
    );
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <h1 className="text-2xl font-bold">预约叫车</h1>

        {!scheduledResp && (
          <>
            <div className="space-y-2">
              <label className="text-sm font-medium">选择上车地点</label>
              <AmapPicker onChange={setLocation} />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">预约时间</label>
              <Input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">车型</label>
              <select
                className="w-full rounded-md border border-gray-300 p-2"
                value={carType}
                onChange={(e) => setCarType(e.target.value)}
              >
                <option value="manual">手动挡</option>
                <option value="auto">自动挡</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">教练等级偏好</label>
              <select
                className="w-full rounded-md border border-gray-300 p-2"
                value={coachLevelPref}
                onChange={(e) => setCoachLevelPref(e.target.value)}
              >
                <option value="ANY">不限</option>
                <option value="A">A级</option>
                <option value="B">B级</option>
                <option value="C">C级</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">服务时长（小时）</label>
              <Input
                type="number"
                min={1}
                max={8}
                value={duration}
                onChange={(e) => setDuration(parseInt(e.target.value) || 1)}
              />
            </div>

            {error && <p className="text-sm text-red-500">{error}</p>}

            <Button
              className="w-full"
              onClick={handleSubmit}
              disabled={createOrder.isPending}
            >
              {createOrder.isPending ? "提交中..." : "查找教练"}
            </Button>

            <Button variant="ghost" className="w-full" onClick={() => router.push("/dashboard")}>
              返回
            </Button>
          </>
        )}

        {scheduledResp && (
          <div className="space-y-4">
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-medium mb-3">推荐教练（Top3）</h2>
              <p className="text-sm text-gray-500 mb-3">
                请选择一位教练，支付定金后等待教练确认。
              </p>
              <div className="space-y-2">
                {scheduledResp.candidates.map((coachId) => (
                  <div
                    key={coachId}
                    className="flex items-center justify-between border rounded-md p-3"
                  >
                    <span className="text-sm">{coachId}</span>
                    <Button
                      size="sm"
                      onClick={() => handleSelectCoach(coachId)}
                      disabled={selectCoach.isPending}
                    >
                      {selectCoach.isPending ? "选择中..." : "选择"}
                    </Button>
                  </div>
                ))}
                {scheduledResp.candidates.length === 0 && (
                  <p className="text-sm text-gray-500">暂无匹配教练</p>
                )}
              </div>
            </div>
            <Button variant="ghost" className="w-full" onClick={() => router.push("/dashboard")}>
              返回
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：验证 TypeScript 编译**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx tsc --noEmit`
预期：无错误

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/escort/student/book-scheduled/page.tsx
git commit -m "feat(web): add book-scheduled page with Top3 candidate selection"
```

---

## 任务 9：Mock 支付组件

**文件：**
- 创建：`web/src/components/mock-payment.tsx`

- [ ] **步骤 1：创建 Mock 支付组件**

创建 `web/src/components/mock-payment.tsx`：

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useMockPay, usePayment } from "@/hooks/use-scheduled";

interface MockPaymentProps {
  dealId: string;
  onPaid: () => void;
}

export function MockPayment({ dealId, onPaid }: MockPaymentProps) {
  const mockPay = useMockPay();
  const { data: payment, isLoading } = usePayment(dealId);
  const [error, setError] = useState("");

  // 已支付
  if (payment?.status === "paid") {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
        <p className="text-green-800">定金已支付</p>
        <p className="text-sm text-gray-500 mt-1">等待教练确认...</p>
      </div>
    );
  }

  const handlePay = async () => {
    setError("");
    mockPay.mutate(
      { dealId },
      {
        onSuccess: () => onPaid(),
        onError: (e: any) => setError(e.message || "支付失败"),
      }
    );
  };

  return (
    <div className="bg-white rounded-lg border p-4 space-y-3">
      <h3 className="font-medium">支付定金</h3>
      <p className="text-sm text-gray-500">
        Mock 支付（开发环境模拟，点击即支付成功）
      </p>
      {error && <p className="text-sm text-red-500">{error}</p>}
      <Button className="w-full" onClick={handlePay} disabled={mockPay.isPending || isLoading}>
        {mockPay.isPending ? "支付中..." : "Mock 支付定金"}
      </Button>
    </div>
  );
}
```

- [ ] **步骤 2：验证 TypeScript 编译**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx tsc --noEmit`
预期：无错误

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/components/mock-payment.tsx
git commit -m "feat(web): add MockPayment component for scheduled order deposit"
```

---

## 任务 10：扩展学员订单详情页（预约单分支）

**文件：**
- 修改：`web/src/app/(protected)/escort/student/orders/[id]/page.tsx`

- [ ] **步骤 1：修改学员订单详情页**

将 `web/src/app/(protected)/escort/student/orders/[id]/page.tsx` 替换为：

```tsx
"use client";

import { useParams, useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
import { useDeal, usePayment } from "@/hooks/use-scheduled";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { ReviewForm } from "@/components/review-form";
import { MockPayment } from "@/components/mock-payment";
import { Button } from "@/components/ui/button";
import type { OrderStatus } from "@/types/escort";

export default function StudentOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuthStore();
  const taskId = params.id as string;
  const { data: order, isLoading } = useOrder(taskId);
  const { data: reviews } = useReviews(taskId);
  const invalidate = useInvalidateOrder(taskId);
  const { orderStatusUpdates } = useOrderRealtimeStore();

  // 预约单：查询 deal 和 payment
  const dealId = order?.deal_id;
  const { data: deal } = useDeal(dealId);
  const { data: payment } = usePayment(dealId);

  // WS 事件 → 刷新
  useWsEvent("task.assigned", () => invalidate());
  useWsEvent("task.in_service", () => invalidate());
  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());
  useWsEvent("deal.confirmed", () => invalidate());
  useWsEvent("deal.rejected", () => invalidate());
  useWsEvent("deal.cancelled", () => invalidate());
  useWsEvent("payment.paid", () => invalidate());

  const currentStatus = orderStatusUpdates[taskId] || order?.status;
  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);
  const isScheduled = order?.order_type === "SCHEDULED";

  if (isLoading) return <div className="p-4">加载中...</div>;
  if (!order) return <div className="p-4">订单不存在</div>;

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">订单详情</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/student/orders")}>返回</Button>
        </div>

        <div className="bg-white rounded-lg border p-4 space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-500">状态</span>
            <OrderStatusBadge status={currentStatus as OrderStatus} />
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">类型</span>
            <span>{isScheduled ? "预约单" : "实时单"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">车型</span>
            <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">时长</span>
            <span>{order.duration_hours}小时</span>
          </div>
          {isScheduled && order.scheduled_at && (
            <div className="flex justify-between">
              <span className="text-gray-500">预约时间</span>
              <span>{new Date(order.scheduled_at).toLocaleString("zh-CN")}</span>
            </div>
          )}
          {order.assigned_resource_id && (
            <div className="flex justify-between">
              <span className="text-gray-500">教练</span>
              <span>{order.assigned_resource_id}</span>
            </div>
          )}
          {deal && (
            <div className="flex justify-between">
              <span className="text-gray-500">交易状态</span>
              <span className="text-sm">{deal.status}</span>
            </div>
          )}
        </div>

        {/* 实时单：等待接单 */}
        {!isScheduled && currentStatus === "published" && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
            <p className="text-yellow-800">等待教练接单...</p>
          </div>
        )}

        {/* 预约单：已选教练，待支付定金 */}
        {isScheduled && dealId && deal?.status === "pending" && payment?.status !== "paid" && (
          <MockPayment dealId={dealId} onPaid={invalidate} />
        )}

        {/* 预约单：已支付，等待教练确认 */}
        {isScheduled && payment?.status === "paid" && deal?.status === "pending" && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
            <p className="text-yellow-800">定金已支付，等待教练确认...</p>
          </div>
        )}

        {/* 预约单：教练已确认，等待签到 */}
        {isScheduled && deal?.status === "active" && currentStatus === "assigned" && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-center">
            <p className="text-blue-800">教练已确认，等待服务开始...</p>
          </div>
        )}

        {/* 预约单：教练拒绝 */}
        {isScheduled && deal?.status === "cancelled" && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center">
            <p className="text-red-800">教练已拒绝，订单已取消</p>
          </div>
        )}

        {/* 评价 */}
        {currentStatus === "completed" && !hasReviewed && user && (
          <div className="bg-white rounded-lg border p-4">
            <ReviewForm
              taskId={taskId}
              reviewerId={user.user_id}
              reviewerRole="STUDENT"
              onSubmitted={invalidate}
            />
          </div>
        )}

        {currentStatus === "completed" && hasReviewed && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
            <p className="text-green-800">已评价</p>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：验证 TypeScript 编译**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx tsc --noEmit`
预期：无错误

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/escort/student/orders/\[id\]/page.tsx
git commit -m "feat(web): extend student order detail for scheduled flow"
```

---

## 任务 11：扩展教练订单详情页（预约单分支）

**文件：**
- 修改：`web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`

- [ ] **步骤 1：修改教练订单详情页**

将 `web/src/app/(protected)/escort/coach/orders/[id]/page.tsx` 替换为：

```tsx
"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
import { useDeal, useConfirmDeal, useRejectDeal } from "@/hooks/use-scheduled";
import { useWsEvent } from "@/hooks/use-ws-events";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { ReviewForm } from "@/components/review-form";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import type { OrderStatus } from "@/types/escort";

export default function CoachOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuthStore();
  const taskId = params.id as string;
  const { data: order, isLoading } = useOrder(taskId);
  const { data: reviews } = useReviews(taskId);
  const invalidate = useInvalidateOrder(taskId);
  const [actionLoading, setActionLoading] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);

  const dealId = order?.deal_id;
  const { data: deal } = useDeal(dealId);
  const confirmDeal = useConfirmDeal();
  const rejectDeal = useRejectDeal();

  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());
  useWsEvent("deal.confirmed", () => invalidate());
  useWsEvent("deal.rejected", () => invalidate());
  useWsEvent("payment.paid", () => invalidate());

  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);
  const isScheduled = order?.order_type === "SCHEDULED";

  const handleCheckIn = async () => {
    setActionLoading(true);
    try {
      await apiClient.post(`/escort/orders/${taskId}/check-in`, {
        coach_id: user?.user_id,
        lat: 39.9,
        lng: 116.4,
      });
      invalidate();
    } finally {
      setActionLoading(false);
    }
  };

  const handleCheckOut = async () => {
    setActionLoading(true);
    try {
      await apiClient.post(`/escort/orders/${taskId}/check-out`, {
        coach_id: user?.user_id,
        lat: 39.9,
        lng: 116.4,
      });
      invalidate();
    } finally {
      setActionLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!dealId || !user?.user_id) return;
    setActionLoading(true);
    try {
      await confirmDeal.mutateAsync({ dealId, coachId: user.user_id });
      invalidate();
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!dealId || !user?.user_id) return;
    setActionLoading(true);
    try {
      await rejectDeal.mutateAsync({
        dealId,
        coachId: user.user_id,
        reason: rejectReason,
      });
      invalidate();
    } finally {
      setActionLoading(false);
      setShowReject(false);
    }
  };

  if (isLoading) return <div className="p-4">加载中...</div>;
  if (!order) return <div className="p-4">订单不存在</div>;

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">订单详情</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/coach/orders")}>返回</Button>
        </div>

        <div className="bg-white rounded-lg border p-4 space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-500">状态</span>
            <OrderStatusBadge status={order.status as OrderStatus} />
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">类型</span>
            <span>{isScheduled ? "预约单" : "实时单"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">学员</span>
            <span>{order.demander_id}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">车型</span>
            <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">时长</span>
            <span>{order.duration_hours}小时</span>
          </div>
          {isScheduled && order.scheduled_at && (
            <div className="flex justify-between">
              <span className="text-gray-500">预约时间</span>
              <span>{new Date(order.scheduled_at).toLocaleString("zh-CN")}</span>
            </div>
          )}
          {deal && (
            <div className="flex justify-between">
              <span className="text-gray-500">交易状态</span>
              <span className="text-sm">{deal.status}</span>
            </div>
          )}
        </div>

        {/* 预约单：待确认（deal pending + 已支付） */}
        {isScheduled && deal?.status === "pending" && (
          <div className="space-y-3">
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-yellow-800 text-sm">学员已支付定金，请确认是否接单。</p>
            </div>
            {!showReject ? (
              <div className="flex gap-2">
                <Button
                  className="flex-1"
                  onClick={handleConfirm}
                  disabled={actionLoading}
                >
                  {actionLoading ? "确认中..." : "确认接单"}
                </Button>
                <Button
                  variant="destructive"
                  className="flex-1"
                  onClick={() => setShowReject(true)}
                  disabled={actionLoading}
                >
                  拒绝
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                <textarea
                  className="w-full rounded-md border border-gray-300 p-2 text-sm"
                  placeholder="拒绝原因..."
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  rows={2}
                />
                <div className="flex gap-2">
                  <Button
                    variant="destructive"
                    className="flex-1"
                    onClick={handleReject}
                    disabled={actionLoading}
                  >
                    {actionLoading ? "提交中..." : "确认拒绝"}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setShowReject(false)}
                    disabled={actionLoading}
                  >
                    取消
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 签到按钮（实时单 assigned 或 预约单 deal active + task assigned） */}
        {order.status === "assigned" && (!isScheduled || deal?.status === "active") && (
          <Button className="w-full" onClick={handleCheckIn} disabled={actionLoading}>
            {actionLoading ? "签到中..." : "签到"}
          </Button>
        )}
        {order.status === "in_progress" && (
          <Button className="w-full" onClick={handleCheckOut} disabled={actionLoading}>
            {actionLoading ? "签退中..." : "签退"}
          </Button>
        )}

        {/* 评价 */}
        {order.status === "completed" && !hasReviewed && user && (
          <div className="bg-white rounded-lg border p-4">
            <ReviewForm
              taskId={taskId}
              reviewerId={user.user_id}
              reviewerRole="COACH"
              onSubmitted={invalidate}
            />
          </div>
        )}
        {order.status === "completed" && hasReviewed && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
            <p className="text-green-800">已评价</p>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：验证 TypeScript 编译**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx tsc --noEmit`
预期：无错误

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/escort/coach/orders/\[id\]/page.tsx
git commit -m "feat(web): extend coach order detail for scheduled confirm/reject"
```

---

## 任务 12：Dashboard 入口 + 前端测试 + 端到端验证

**文件：**
- 修改：`web/src/app/(protected)/dashboard/page.tsx`
- 创建：`web/tests/scheduled-flow.test.ts`

- [ ] **步骤 1：在 Dashboard 学员入口添加"预约叫车"按钮**

修改 `web/src/app/(protected)/dashboard/page.tsx`，在 `{activeRole === "demander" && (` 块内，"实时叫车" Button 之后添加：

```tsx
              <Button variant="outline" onClick={() => router.push("/escort/student/book-scheduled")}>
                预约叫车
              </Button>
```

修改后的 demander 块：
```tsx
          {activeRole === "demander" && (
            <>
              <Button onClick={() => router.push("/escort/student/book-instant")}>
                实时叫车
              </Button>
              <Button variant="outline" onClick={() => router.push("/escort/student/book-scheduled")}>
                预约叫车
              </Button>
              <Button variant="outline" onClick={() => router.push("/escort/student/orders")}>
                我的订单
              </Button>
            </>
          )}
```

- [ ] **步骤 2：编写前端单元测试**

创建 `web/tests/scheduled-flow.test.ts`：

```typescript
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useCreateScheduledOrder, useSelectCoach, useMockPay, useConfirmDeal, useRejectDeal } from "@/hooks/use-scheduled";

// Mock apiClient
vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from "@/lib/api-client";

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("Scheduled flow hooks", () => {
  it("useCreateScheduledOrder calls POST /escort/orders", async () => {
    (apiClient.post as any).mockResolvedValue({
      task_id: "task_1",
      order_type: "SCHEDULED",
      candidates: ["coach_1", "coach_2"],
    });
    const { result } = renderHook(() => useCreateScheduledOrder(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({
        demander_id: "u1",
        origin_lat: 39.9,
        origin_lng: 116.4,
        car_type: "manual",
        duration_hours: 2,
        scheduled_at: "2026-08-10T10:00:00",
        coach_level_pref: "ANY",
      });
    });
    expect(apiClient.post).toHaveBeenCalledWith("/escort/orders", expect.objectContaining({
      order_type: "SCHEDULED",
    }));
  });

  it("useSelectCoach calls POST /escort/orders/{id}/select-coach", async () => {
    (apiClient.post as any).mockResolvedValue({
      deal_id: "deal_1",
      task_id: "task_1",
      resource_id: "coach_1",
      status: "pending",
      deposit_amount: 48.0,
    });
    const { result } = renderHook(() => useSelectCoach(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ taskId: "task_1", resourceId: "coach_1" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/orders/task_1/select-coach",
      { resource_id: "coach_1" }
    );
  });

  it("useMockPay calls POST /escort/payments/mock-pay", async () => {
    (apiClient.post as any).mockResolvedValue({
      payment_id: "pay_1",
      deal_id: "deal_1",
      user_id: "u1",
      amount: 48.0,
      payment_type: "deposit",
      status: "paid",
      trade_no: "mock_trade_pay_1",
    });
    const { result } = renderHook(() => useMockPay(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ dealId: "deal_1" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/payments/mock-pay",
      { deal_id: "deal_1", payment_type: "deposit" }
    );
  });

  it("useConfirmDeal calls POST /escort/deals/{id}/confirm", async () => {
    (apiClient.post as any).mockResolvedValue({
      deal_id: "deal_1",
      status: "active",
      task_id: "task_1",
    });
    const { result } = renderHook(() => useConfirmDeal(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ dealId: "deal_1", coachId: "coach_1" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/deals/deal_1/confirm",
      { coach_id: "coach_1" }
    );
  });

  it("useRejectDeal calls POST /escort/deals/{id}/reject", async () => {
    (apiClient.post as any).mockResolvedValue({
      deal_id: "deal_1",
      status: "cancelled",
      task_id: "task_1",
    });
    const { result } = renderHook(() => useRejectDeal(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ dealId: "deal_1", coachId: "coach_1", reason: "时间冲突" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/deals/deal_1/reject",
      { coach_id: "coach_1", reason: "时间冲突" }
    );
  });
});
```

- [ ] **步骤 3：运行前端测试**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx vitest run tests/scheduled-flow.test.ts`
预期：5 个测试全部 PASS

- [ ] **步骤 4：验证 TypeScript 编译**

运行：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx tsc --noEmit`
预期：无错误

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/dashboard/page.tsx web/tests/scheduled-flow.test.ts
git commit -m "feat(web): add book-scheduled dashboard entry and scheduled flow tests"
```

---

## 任务 13：端到端验证

**文件：** 无（手动验证 + 截图）

- [ ] **步骤 1：启动后端**

运行：
```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
set UMCP_JWT_SECRET=test-secret-12345
set UMCP_PLUGINS=escort_driving
python -m umcp_core.transport
```
预期：服务在 `http://localhost:8000` 启动，输出 `[UMCP] 已加载插件: escort_driving`

- [ ] **步骤 2：启动前端**

运行：
```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npm run dev
```
预期：前端在 `http://localhost:3000` 启动

- [ ] **步骤 3：验证预约单全流程**

在浏览器中执行以下场景：

1. **学员登录** → Dashboard 显示"预约叫车"按钮
2. **点击"预约叫车"** → 进入 book-scheduled 页面，选择地点、时间、车型、等级偏好
3. **点击"查找教练"** → 显示 Top3 候选教练列表
4. **选择一位教练** → 跳转到订单详情页，显示"支付定金"组件
5. **点击"Mock 支付定金"** → 显示"定金已支付，等待教练确认"
6. **切换到教练角色** → 教练订单列表应显示该预约单
7. **教练进入订单详情** → 显示"确认接单"和"拒绝"按钮
8. **教练点击"确认接单"** → 交易状态变为 active，显示"签到"按钮
9. **教练签到** → 状态变为 in_progress，显示"签退"按钮
10. **教练签退** → 状态变为 completed
11. **学员评价教练** → 评价表单出现，提交成功
12. **教练评价学员** → 评价表单出现，提交成功

- [ ] **步骤 4：验证教练拒绝流程**

重复步骤 1-5，然后在步骤 7 中教练点击"拒绝"：
- 输入拒绝原因
- 点击"确认拒绝"
- 学员端订单详情显示"教练已拒绝，订单已取消"

- [ ] **步骤 5：运行全部测试确保无回归**

后端：`cd c:\trae_projects\tongyongjiaoyi\umcp-core && python -m pytest tests/ -x -q`
前端：`cd c:\trae_projects\tongyongjiaoyi\umcp-core\web && npx vitest run`

预期：全部通过

- [ ] **步骤 6：Commit 验证记录**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git log --oneline -15
```

确认所有任务的 commit 都已记录。

---

## 自检

### 1. 规格覆盖度

对照规格 `docs/specs/2026-08-01-escort-core-loop-design.md` 第 3.3 节"预约单流程"：

| 规格步骤 | 实现任务 | 状态 |
|---------|---------|------|
| 1. 学员 POST /orders (SCHEDULED) → Top3 | 已有（切片1已实现 SCHEDULED 分支） | ✅ |
| 2. 学员 POST /orders/{id}/select-coach | 任务 3 | ✅ |
| 3. 学员 POST /payments/mock-pay | 任务 4 | ✅ |
| 4. 教练 POST /deals/{id}/confirm 或 /reject | 任务 5 | ✅ |
| 5-7. 签到→签退→评价（复用实时单） | 已有（切片1已实现） | ✅ |
| WS 推送 deal.created/deal.paid/deal.confirmed/deal.cancelled | 任务 1-5（EventType 已存在 + WS_PUSHABLE_EVENTS 已含） | ✅ |
| 前端 book-scheduled 页面 | 任务 8 | ✅ |
| 前端 Mock 支付 | 任务 9 | ✅ |
| 前端教练确认/拒绝 | 任务 11 | ✅ |
| 前端学员订单详情（预约单分支） | 任务 10 | ✅ |
| Dashboard 预约入口 | 任务 12 | ✅ |
| 端到端验证 | 任务 13 | ✅ |

### 2. 占位符扫描

- ✅ 无"待定"/"TODO"/"后续实现"
- ✅ 所有代码步骤都包含完整代码块
- ✅ 无"类似任务 N"引用
- ✅ 所有测试都包含实际测试代码

### 3. 类型一致性

- `SelectCoachResponse.deal_id` / `deal_id` 在任务 3（后端）和任务 7（前端类型）一致
- `PaymentInfo.status` 值 "paid" 在任务 4（后端）和任务 9（前端 MockPayment 判断）一致
- `DealInfo.status` 值 "pending"/"active"/"cancelled" 在任务 5（后端）和任务 10/11（前端判断）一致
- `useMockPay` 参数 `{ dealId, paymentType? }` 在任务 7 和任务 9 一致
- `useConfirmDeal`/`useRejectDeal` 参数 `{ dealId, coachId }` 在任务 7 和任务 11 一致
- 后端端点路径 `/api/v1/escort/payments/mock-pay`、`/api/v1/escort/deals/{id}/confirm`、`/api/v1/escort/deals/{id}/reject`、`/api/v1/escort/orders/{id}/select-coach` 在所有任务中一致
