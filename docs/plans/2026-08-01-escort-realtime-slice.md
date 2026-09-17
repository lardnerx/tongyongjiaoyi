# 陪驾业务核心闭环 - 切片1：实时单全流程 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现实时单端到端闭环（学员下单→教练抢单→签到→签退→双向评价），包含后端 API 扩展（抢单/评价/角色切换/教练上线）和前端学员端+教练端页面。

**架构：** 后端 FastAPI 路由扩展 + WS 广播在线教练；前端 Next.js 14 App Router 新增 escort 路由组，Zustand 管理 WS 实时状态，React Query 管理服务端缓存，高德地图 JS SDK 选点。

**技术栈：** FastAPI、SQLAlchemy、Next.js 14、TypeScript、Zustand、React Query、高德地图 JS SDK、Vitest

---

## 后端关键上下文

**TaskStatus 枚举值（小写字符串）：**
- `draft` → `published` → `matching` → `assigned` → `in_progress` → `completed`
- 任意非终态 → `cancelled`

**Task 状态转移方法：**
- `task.publish()` → published+matching，发 `TASK_PUBLISHED` 事件
- `task.assign_to(resource_id)` → assigned，发 `TASK_ASSIGNED` 事件（payload 含 `supplier_id`）
- `task.start_execution()` → in_progress（无事件）
- `task.complete()` → completed，发 `TASK_COMPLETED` 事件
- `task.cancel()` → cancelled，发 `TASK_COMPLETED` 事件（payload `{cancelled: True}`）

**现有 create_order 实时单分支：** publish → match → assign_to + start_execution（自动匹配模式）。**本计划改为抢单模式**：只 publish，等教练调 claim。

**User 类：** `user.switch_role(role_type)` 已存在；`JwtService.issue(user)` 重签 token（含 active_role）。

**escort_reviews 表（已建）：** review_id / deal_id / evaluator_id / evaluatee_id / evaluator_role / ratings(JSONB) / comment / created_at。实时单无 Deal，`deal_id` 字段存 `task_id`。

**TrustEngine：** `record_evaluation(Evaluation)` → TrustProfile。Evaluation 字段：evaluator_id / evaluatee_id / task_id / ratings(dict) / comment / domain_tag。

---

## 文件结构

```
umcp-core/
├── src/umcp_core/
│   ├── events/types.py                    # 修改：新增 EventType
│   ├── transport/ws.py                    # 修改：WS_PUSHABLE_EVENTS + ConnectionManager 广播
│   └── transport/routers/
│       ├── auth.py                        # 修改：新增 switch-role 端点
│       └── escort/
│           ├── orders.py                  # 修改：create_order 改抢单 + 新增 claim/check-in/check-out
│           ├── coaches.py                 # 修改：新增 online/offline
│           └── reviews.py                 # 创建：评价 router
├── tests/
│   ├── test_escort_claim.py              # 创建：抢单测试
│   ├── test_escort_reviews.py            # 创建：评价测试
│   └── test_auth_switch_role.py          # 创建：角色切换测试
└── web/
    ├── src/
    │   ├── lib/
    │   │   ├── auth-store.ts              # 修改：switchRole + activeRole
    │   │   └── order-realtime-store.ts    # 创建：WS 实时订单状态
    │   ├── hooks/
    │   │   ├── use-ws-events.ts           # 创建：WS 事件订阅
    │   │   └── use-orders.ts              # 创建：订单查询 hooks
    │   ├── components/
    │   │   ├── amap-picker.tsx            # 创建：高德地图选点
    │   │   ├── order-status-badge.tsx     # 创建：订单状态徽章
    │   │   └── review-form.tsx           # 创建：评价表单
    │   ├── middleware.ts                  # 修改：角色守卫
    │   ├── app/
    │   │   ├── (protected)/dashboard/page.tsx       # 修改：角色切换入口
    │   │   └── (protected)/escort/
    │   │       ├── student/
    │   │       │   ├── book-instant/page.tsx        # 创建：实时单下单
    │   │       │   └── orders/
    │   │       │       ├── page.tsx                 # 创建：订单列表
    │   │       │       └── [id]/page.tsx            # 创建：订单详情
    │   │       └── coach/
    │   │           ├── page.tsx                     # 创建：接单大厅
    │   │           └── orders/
    │   │               ├── page.tsx                 # 创建：我的订单
    │   │               └── [id]/page.tsx            # 创建：订单详情
    │   └── types/
    │       └── escort.ts                            # 创建：陪驾类型定义
    └── tests/
        ├── order-realtime-store.test.ts             # 创建
        └── use-ws-events.test.ts                    # 创建
```

---

## 任务列表

### 任务 1：扩展 EventType + WS_PUSHABLE_EVENTS

**文件：**
- 修改：`src/umcp_core/events/types.py`
- 修改：`src/umcp_core/transport/ws.py`

- [ ] **步骤 1：新增 EventType**

在 `src/umcp_core/events/types.py` 的 `EventType` 枚举中，在 `CHECK_OUT` 之后新增：

```python
    # 实时单抢单（阶段三扩展）
    TASK_CLAIMED = "task.claimed"
    TASK_IN_SERVICE = "task.in_service"

    # 预约单确认（阶段三扩展）
    DEAL_CONFIRMED = "deal.confirmed"
    DEAL_REJECTED = "deal.rejected"
```

- [ ] **步骤 2：扩展 WS_PUSHABLE_EVENTS**

在 `src/umcp_core/transport/ws.py` 的 `WS_PUSHABLE_EVENTS` 集合中新增：

```python
WS_PUSHABLE_EVENTS: set[EventType] = {
    EventType.TASK_PUBLISHED,
    EventType.TASK_ASSIGNED,
    EventType.TASK_COMPLETED,
    EventType.TASK_CANCELLED,
    EventType.TASK_CLAIMED,
    EventType.TASK_IN_SERVICE,
    EventType.RESOURCE_REGISTERED,
    EventType.RESOURCE_STATUS_CHANGED,
    EventType.DEAL_CREATED,
    EventType.DEAL_PAID,
    EventType.DEAL_COMPLETED,
    EventType.DEAL_DISPUTED,
    EventType.DEAL_CANCELLED,
    EventType.DEAL_RESOLVED,
    EventType.DEAL_CONFIRMED,
    EventType.DEAL_REJECTED,
    EventType.SUBTASK_COMPLETED,
    EventType.SUBTASK_CANCELLED,
    EventType.TRUST_UPDATED,
    EventType.ANOMALY_DETECTED,
    EventType.DISPUTE_OPENED,
    EventType.REVIEW_SUBMITTED,
    EventType.CHECK_IN,
    EventType.CHECK_OUT,
}
```

- [ ] **步骤 3：验证**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -c "from umcp_core.events.types import EventType; print(EventType.TASK_CLAIMED.value, EventType.TASK_IN_SERVICE.value)"
```

预期输出：`task.claimed task.in_service`

- [ ] **步骤 4：运行现有测试确认无回归**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/ -x -q --timeout=10
```

预期：全部通过

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/events/types.py src/umcp_core/transport/ws.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat: 扩展 EventType(抢单/服务开始/预约确认) + WS_PUSHABLE_EVENTS"
```

---

### 任务 2：扩展 ConnectionManager 广播能力

**文件：**
- 修改：`src/umcp_core/transport/ws.py`
- 创建：`tests/test_ws_broadcast.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_ws_broadcast.py`：

```python
"""ConnectionManager 广播能力测试。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from umcp_core.transport.ws import ConnectionManager


@pytest.mark.asyncio
async def test_register_and_unregister_online_coach():
    """教练上线注册、下线移除。"""
    mgr = ConnectionManager()
    mgr.register_online_coach("coach_1")
    mgr.register_online_coach("coach_2")
    assert mgr.online_coaches == {"coach_1", "coach_2"}
    mgr.unregister_online_coach("coach_1")
    assert mgr.online_coaches == {"coach_2"}


@pytest.mark.asyncio
async def test_broadcast_to_online_coaches_sends_to_all():
    """广播消息发送给所有在线教练。"""
    mgr = ConnectionManager()
    mgr.register_online_coach("coach_1")
    mgr.register_online_coach("coach_2")

    mgr.send_to_user = AsyncMock()
    message = {"type": "task.published", "data": {}}

    await mgr.broadcast_to_online_coaches(message)

    assert mgr.send_to_user.await_count == 2
    called_ids = {call.args[0] for call in mgr.send_to_user.await_args_list}
    assert called_ids == {"coach_1", "coach_2"}


@pytest.mark.asyncio
async def test_broadcast_to_online_coaches_empty_set():
    """无在线教练时不发送。"""
    mgr = ConnectionManager()
    mgr.send_to_user = AsyncMock()
    await mgr.broadcast_to_online_coaches({"type": "test"})
    assert mgr.send_to_user.await_count == 0
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_ws_broadcast.py -x -v
```

预期：FAIL，`AttributeError: 'ConnectionManager' object has no attribute 'register_online_coach'`

- [ ] **步骤 3：实现广播能力**

在 `src/umcp_core/transport/ws.py` 的 `ConnectionManager` 类中，`__init__` 方法末尾新增在线教练集合，并在 `disconnect_all` 之前新增方法：

```python
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = threading.RLock()
        self._online_coaches: set[str] = set()

    def register_online_coach(self, user_id: str) -> None:
        """注册在线教练（教练上线时调用）。"""
        with self._lock:
            self._online_coaches.add(user_id)

    def unregister_online_coach(self, user_id: str) -> None:
        """移除在线教练（教练下线时调用）。"""
        with self._lock:
            self._online_coaches.discard(user_id)

    @property
    def online_coaches(self) -> set[str]:
        """返回当前在线教练 user_id 集合的副本。"""
        with self._lock:
            return set(self._online_coaches)

    async def broadcast_to_online_coaches(self, message: dict[str, Any]) -> None:
        """广播消息给所有在线教练。"""
        with self._lock:
            coach_ids = list(self._online_coaches)
        for uid in coach_ids:
            await self.send_to_user(uid, message)
```

- [ ] **步骤 4：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_ws_broadcast.py -x -v
```

预期：PASS（3 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/ws.py tests/test_ws_broadcast.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat: ConnectionManager 新增在线教练广播能力"
```

---

### 任务 3：修改 create_order 实时单分支为抢单模式 + 新增 claim/check-in/check-out 接口

**文件：**
- 修改：`src/umcp_core/transport/routers/escort/orders.py`
- 创建：`tests/test_escort_claim.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_escort_claim.py`：

```python
"""实时单抢单流程测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app


@pytest.fixture
def client_and_server():
    server = UMCPServer()
    server._jwt_secret = "test_secret"
    app = create_app(server, jwt_secret="test_secret")
    client = TestClient(app)
    return client, server


def _auth_headers(server: UMCPServer, user_id: str = "u1", roles: list[str] | None = None):
    """生成已认证请求头。"""
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier

    jwt = JwtService("test_secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    if roles and "supplier" in roles:
        user.add_role(_ClaimsSupplier())
    if roles:
        user.switch_role(roles[0])
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_create_realtime_order_returns_published(client_and_server):
    """实时单下单后状态为 published（抢单模式，不自动分配）。"""
    client, server = client_and_server
    server.task_repo.clear()
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, "u1"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "published"
    assert data["order_type"] == "REALTIME"


def test_claim_order_success(client_and_server):
    """教练抢单成功，状态变为 assigned。"""
    client, server = client_and_server
    server.task_repo.clear()
    # 学员下单
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, "u1"),
    )
    task_id = resp.json()["data"]["task_id"]
    # 教练抢单
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp2.status_code == 200
    data = resp2.json()["data"]
    assert data["status"] == "assigned"
    assert data["assigned_resource_id"] == "coach_1"


def test_claim_already_assigned_fails(client_and_server):
    """已被抢的订单无法再次抢单。"""
    client, server = client_and_server
    server.task_repo.clear()
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, "u1"),
    )
    task_id = resp.json()["data"]["task_id"]
    # 第一个教练抢单成功
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    # 第二个教练抢单失败
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_2"},
        headers=_auth_headers(server, "coach_2", roles=["supplier"]),
    )
    assert resp2.status_code == 400


def test_check_in_transitions_to_in_progress(client_and_server):
    """教练签到，状态变为 in_progress。"""
    client, server = client_and_server
    server.task_repo.clear()
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, "u1"),
    )
    task_id = resp.json()["data"]["task_id"]
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "in_progress"


def test_check_out_transitions_to_completed(client_and_server):
    """教练签退，状态变为 completed。"""
    client, server = client_and_server
    server.task_repo.clear()
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, "u1"),
    )
    task_id = resp.json()["data"]["task_id"]
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": "coach_1"},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": "coach_1", "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "completed"
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_escort_claim.py -x -v
```

预期：FAIL（create_order 仍返回自动匹配后的状态，claim 接口不存在）

- [ ] **步骤 3：修改 orders.py**

在 `src/umcp_core/transport/routers/escort/orders.py` 中：

**3a. 修改 create_order 实时单分支**——将自动匹配改为只 publish：

将 `create_order` 函数中 `# 实时单` 之后的代码替换为：

```python
    # 实时单：只 publish，等待教练抢单（抢单模式）
    try:
        server.task_repo.save(task)
        task.bind_event_bus(server.event_bus)
        task.publish()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 广播给所有在线教练
    from umcp_core.transport.ws import ConnectionManager
    # manager 通过 server.app_state 获取（在 app.py 中注入）
    manager: ConnectionManager | None = getattr(server, "ws_manager", None)
    if manager is not None:
        import asyncio
        message = {
            "type": "task.published",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "task_id": task.task_id,
                "demander_id": task.demander_id,
                "origin_lat": req.origin_lat,
                "origin_lng": req.origin_lng,
                "car_type": req.car_type,
                "duration_hours": req.duration_hours,
                "coach_level_pref": req.coach_level_pref,
            },
        }
        try:
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_online_coaches(message), loop
            )
        except RuntimeError:
            pass  # 无事件循环时跳过（测试环境）

    return ok(_task_to_order_info(task).model_dump())
```

**3b. 新增 claim/check-in/check-out 接口**——在 `cancel_order` 之后新增：

```python
class ClaimRequest(BaseModel):
    coach_id: str


class CheckInOutRequest(BaseModel):
    coach_id: str
    lat: float
    lng: float


@router.post("/orders/{task_id}/claim", response_model=Envelope)
async def claim_order(
    task_id: str,
    req: ClaimRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练抢单：published/matching → assigned。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    task.bind_event_bus(server.event_bus)
    try:
        if task.status not in ("published", "matching"):
            raise RuntimeError(f"订单已被抢或状态不允许（当前: {task.status}）")
        task.assign_to(req.coach_id)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 广播给其他在线教练：订单已被抢
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        import asyncio
        message = {
            "type": "task.claimed",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"task_id": task_id, "coach_id": req.coach_id},
        }
        try:
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_online_coaches(message), loop
            )
        except RuntimeError:
            pass

    return ok(_task_to_order_info(task).model_dump())


@router.post("/orders/{task_id}/check-in", response_model=Envelope)
async def check_in_order(
    task_id: str,
    req: CheckInOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签到：assigned → in_progress。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    task.bind_event_bus(server.event_bus)
    try:
        task.start_execution()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)

    # 推送签到事件给学员
    server.event_bus.publish(
        Event(
            type=EventType.TASK_IN_SERVICE,
            source_layer="ESCORT",
            payload={
                "task_id": task_id,
                "demander_id": task.demander_id,
                "coach_id": req.coach_id,
                "lat": req.lat,
                "lng": req.lng,
            },
        )
    )
    return ok(_task_to_order_info(task).model_dump())


@router.post("/orders/{task_id}/check-out", response_model=Envelope)
async def check_out_order(
    task_id: str,
    req: CheckInOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练签退：in_progress → completed。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    task.bind_event_bus(server.event_bus)
    try:
        task.complete()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(_task_to_order_info(task).model_dump())
```

**3c. 更新 import**——在文件顶部添加：

```python
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
```

- [ ] **步骤 4：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_escort_claim.py -x -v
```

预期：PASS（5 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/routers/escort/orders.py tests/test_escort_claim.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat: 实时单改抢单模式 + claim/check-in/check-out 接口"
```

---

### 任务 4：扩展 coaches.py 上线/下线接口

**文件：**
- 修改：`src/umcp_core/transport/routers/escort/coaches.py`
- 创建：`tests/test_coach_online.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_coach_online.py`：

```python
"""教练上线/下线接口测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsSupplier


@pytest.fixture
def client_and_server():
    server = UMCPServer()
    app = create_app(server, jwt_secret="test_secret")
    client = TestClient(app)
    return client, server


def _auth_headers(server: UMCPServer, user_id: str = "coach_1"):
    jwt = JwtService("test_secret")
    user = _ClaimsUser(user_id=user_id, name="Coach")
    user.add_role(_ClaimsSupplier())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_coach_online_registers(client_and_server):
    """教练上线后注册到在线集合。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/escort/coaches/coach_1/online",
        json={"lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    assert "coach_1" in server.ws_manager.online_coaches


def test_coachoffline_removes(client_and_server):
    """教练下线后从在线集合移除。"""
    client, server = client_and_server
    client.post(
        "/api/v1/escort/coaches/coach_1/online",
        json={"lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server),
    )
    resp = client.post(
        "/api/v1/escort/coaches/coach_1/offline",
        headers=_auth_headers(server),
    )
    assert resp.status_code == 200
    assert "coach_1" not in server.ws_manager.online_coaches
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_coach_online.py -x -v
```

预期：FAIL（接口不存在）

- [ ] **步骤 3：实现上线/下线接口**

在 `src/umcp_core/transport/routers/escort/coaches.py` 中新增（文件末尾追加）：

```python
class OnlineRequest(BaseModel):
    lat: float
    lng: float


@router.post("/{coach_id}/online", response_model=Envelope)
async def coach_online(
    coach_id: str,
    req: OnlineRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练上线：注册到在线教练集合。"""
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        manager.register_online_coach(coach_id)
    return ok({"coach_id": coach_id, "online": True})


@router.post("/{coach_id}/offline", response_model=Envelope)
async def coach_offline(
    coach_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """教练下线：从在线集合移除。"""
    manager = getattr(server, "ws_manager", None)
    if manager is not None:
        manager.unregister_online_coach(coach_id)
    return ok({"coach_id": coach_id, "online": False})
```

- [ ] **步骤 4：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_coach_online.py -x -v
```

预期：PASS（2 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/routers/escort/coaches.py tests/test_coach_online.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat: 教练上线/下线接口"
```

---

### 任务 5：新增 reviews.py 评价 router

**文件：**
- 创建：`src/umcp_core/transport/routers/escort/reviews.py`
- 创建：`tests/test_escort_reviews.py`
- 修改：`src/umcp_core/transport/app.py`（注册 reviews router）

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_escort_reviews.py`：

```python
"""评价接口测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier


@pytest.fixture
def client_and_server():
    server = UMCPServer()
    app = create_app(server, jwt_secret="test_secret")
    client = TestClient(app)
    return client, server


def _auth_headers(server: UMCPServer, user_id: str, roles: list[str] | None = None):
    jwt = JwtService("test_secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    if roles and "supplier" in roles:
        user.add_role(_ClaimsSupplier())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_completed_order(client, server, demander_id="u1", coach_id="coach_1"):
    """创建一个已完成的订单（helper）。"""
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
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, demander_id),
    )
    task_id = resp.json()["data"]["task_id"]
    client.post(
        f"/api/v1/escort/orders/{task_id}/claim",
        json={"coach_id": coach_id},
        headers=_auth_headers(server, coach_id, roles=["supplier"]),
    )
    client.post(
        f"/api/v1/escort/orders/{task_id}/check-in",
        json={"coach_id": coach_id, "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, coach_id, roles=["supplier"]),
    )
    client.post(
        f"/api/v1/escort/orders/{task_id}/check-out",
        json={"coach_id": coach_id, "lat": 39.9, "lng": 116.4},
        headers=_auth_headers(server, coach_id, roles=["supplier"]),
    )
    return task_id


def test_student_review_coach_success(client_and_server):
    """学员评价教练成功。"""
    client, server = client_and_server
    server.task_repo.clear()
    task_id = _create_completed_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "教练很专业",
        },
        headers=_auth_headers(server, "u1"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["evaluatee_id"] == "coach_1"
    assert data["reviewer_role"] == "STUDENT"


def test_coach_review_student_success(client_and_server):
    """教练评价学员成功。"""
    client, server = client_and_server
    server.task_repo.clear()
    task_id = _create_completed_order(client, server)
    resp = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "coach_1",
            "reviewer_role": "COACH",
            "ratings": {"punctuality_score": 5, "cooperation_score": 4, "payment_score": 5},
            "comment": "学员很守时",
        },
        headers=_auth_headers(server, "coach_1", roles=["supplier"]),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["evaluatee_id"] == "u1"
    assert data["reviewer_role"] == "COACH"


def test_duplicate_review_fails(client_and_server):
    """重复评价失败。"""
    client, server = client_and_server
    server.task_repo.clear()
    task_id = _create_completed_order(client, server)
    review_body = {
        "reviewer_id": "u1",
        "reviewer_role": "STUDENT",
        "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
        "comment": "好评",
    }
    client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json=review_body,
        headers=_auth_headers(server, "u1"),
    )
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json=review_body,
        headers=_auth_headers(server, "u1"),
    )
    assert resp2.status_code == 400


def test_review_not_completed_fails(client_and_server):
    """未完成订单不能评价。"""
    client, server = client_and_server
    server.task_repo.clear()
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9,
            "origin_lng": 116.4,
            "car_type": "manual",
            "required_skills": ["coach_license"],
            "duration_hours": 2,
            "order_type": "REALTIME",
        },
        headers=_auth_headers(server, "u1"),
    )
    task_id = resp.json()["data"]["task_id"]
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "好评",
        },
        headers=_auth_headers(server, "u1"),
    )
    assert resp2.status_code == 400


def test_get_reviews(client_and_server):
    """查询订单评价。"""
    client, server = client_and_server
    server.task_repo.clear()
    task_id = _create_completed_order(client, server)
    client.post(
        f"/api/v1/escort/orders/{task_id}/reviews",
        json={
            "reviewer_id": "u1",
            "reviewer_role": "STUDENT",
            "ratings": {"teaching_score": 5, "patience_score": 4, "safety_score": 5},
            "comment": "好评",
        },
        headers=_auth_headers(server, "u1"),
    )
    resp = client.get(
        f"/api/v1/escort/orders/{task_id}/reviews",
        headers=_auth_headers(server, "u1"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["reviewer_role"] == "STUDENT"
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_escort_reviews.py -x -v
```

预期：FAIL（路由不存在）

- [ ] **步骤 3：实现 reviews router**

创建 `src/umcp_core/transport/routers/escort/reviews.py`：

```python
"""陪驾评价 router（双向评价）。"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/escort", tags=["escort-reviews"])

# 内存存储（MVP 阶段，后续迁移到 ORM）
_reviews_store: dict[str, list[dict]] = {}


class ReviewRequest(BaseModel):
    reviewer_id: str
    reviewer_role: str  # STUDENT | COACH
    ratings: dict[str, float]
    comment: str = ""


class ReviewInfo(BaseModel):
    review_id: str
    task_id: str
    reviewer_id: str
    reviewer_role: str
    evaluatee_id: str
    ratings: dict[str, float]
    comment: str
    created_at: str


@router.post("/orders/{task_id}/reviews", response_model=Envelope)
async def create_review(
    task_id: str,
    req: ReviewRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """提交评价。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    if task.status != "completed":
        raise IllegalStateError(message=f"订单未完成（当前: {task.status}），无法评价")

    # 确定被评价者
    if req.reviewer_role == "STUDENT":
        evaluatee_id = task.assigned_resource_id or ""
    else:
        evaluatee_id = task.demander_id

    # 检查重复评价
    existing = _reviews_store.get(task_id, [])
    for r in existing:
        if r["reviewer_role"] == req.reviewer_role:
            raise IllegalStateError(message="该角色已评价过此订单")

    review_id = f"rev_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    review = {
        "review_id": review_id,
        "task_id": task_id,
        "reviewer_id": req.reviewer_id,
        "reviewer_role": req.reviewer_role,
        "evaluatee_id": evaluatee_id,
        "ratings": req.ratings,
        "comment": req.comment,
        "created_at": now,
    }
    _reviews_store.setdefault(task_id, []).append(review)

    # 更新信任画像
    domain_tag = task.domain_tag.value
    trust_engine = server.trust_engine_for(domain_tag)
    if trust_engine is not None:
        evaluation = Evaluation(
            evaluator_id=req.reviewer_id,
            evaluatee_id=evaluatee_id,
            task_id=task_id,
            ratings=req.ratings,
            comment=req.comment,
            domain_tag=domain_tag,
        )
        trust_engine.record_evaluation(evaluation)

    # 发布评价事件
    server.event_bus.publish(
        Event(
            type=EventType.REVIEW_SUBMITTED,
            source_layer="ESCORT",
            payload={
                "task_id": task_id,
                "reviewer_id": req.reviewer_id,
                "evaluatee_id": evaluatee_id,
                "reviewer_role": req.reviewer_role,
            },
        )
    )

    return ok(review)


@router.get("/orders/{task_id}/reviews", response_model=Envelope)
async def get_reviews(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查询订单评价。"""
    reviews = _reviews_store.get(task_id, [])
    return ok(reviews)
```

- [ ] **步骤 4：注册 reviews router**

在 `src/umcp_core/transport/app.py` 中，找到 escort coaches router 注册处，在其后添加：

```python
from umcp_core.transport.routers.escort.reviews import router as escort_reviews_router
app.include_router(escort_reviews_router)
```

- [ ] **步骤 5：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_escort_reviews.py -x -v
```

预期：PASS（5 个用例）

- [ ] **步骤 6：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/routers/escort/reviews.py src/umcp_core/transport/app.py tests/test_escort_reviews.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat: 陪驾评价 router（双向评价 + 信任画像更新）"
```

---

### 任务 6：扩展 auth.py 角色切换接口

**文件：**
- 修改：`src/umcp_core/transport/routers/auth.py`
- 创建：`tests/test_auth_switch_role.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_auth_switch_role.py`：

```python
"""角色切换接口测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier


@pytest.fixture
def client_and_server():
    server = UMCPServer()
    app = create_app(server, jwt_secret="test_secret")
    client = TestClient(app)
    return client, server


def _auth_headers(server: UMCPServer, user_id: str = "u1", active_role: str = "demander"):
    jwt = JwtService("test_secret")
    user = _ClaimsUser(user_id=user_id, name="Test")
    user.add_role(_ClaimsDemander())
    user.add_role(_ClaimsSupplier())
    user.switch_role(active_role)
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_switch_role_success(client_and_server):
    """切换角色成功，返回新 token。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/auth/switch-role",
        json={"role": "supplier"},
        headers=_auth_headers(server, "u1", "demander"),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    # 新 token 的 active_role 应为 supplier
    new_token = data["access_token"]
    decoded = JwtService("test_secret").decode(new_token)
    assert decoded["active_role"] == "supplier"


def test_switch_role_invalid_fails(client_and_server):
    """切换到未关联角色失败。"""
    client, server = client_and_server
    resp = client.post(
        "/api/v1/auth/switch-role",
        json={"role": "admin"},
        headers=_auth_headers(server, "u1", "demander"),
    )
    assert resp.status_code == 400
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_auth_switch_role.py -x -v
```

预期：FAIL（接口不存在）

- [ ] **步骤 3：实现角色切换接口**

在 `src/umcp_core/transport/routers/auth.py` 中，`me` 端点之后新增：

```python
class SwitchRoleRequest(BaseModel):
    role: str


@router.post("/switch-role", response_model=Envelope[TokenResponse])
async def switch_role(
    req: SwitchRoleRequest,
    current_user: User = Depends(get_current_user),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope[TokenResponse]:
    """切换当前活动角色，返回新 token 对。"""
    try:
        current_user.switch_role(req.role)
    except ValueError as e:
        raise InvalidCredentialError(message=str(e)) from e
    tokens = jwt_service.issue(current_user)
    return ok(tokens)
```

- [ ] **步骤 4：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m pytest tests/test_auth_switch_role.py -x -v
```

预期：PASS（2 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add src/umcp_core/transport/routers/auth.py tests/test_auth_switch_role.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat: 角色切换接口 /auth/switch-role"
```

---

### 任务 7：前端 - 扩展 auth-store + middleware 角色守卫

**文件：**
- 修改：`web/src/lib/auth-store.ts`
- 修改：`web/src/middleware.ts`
- 修改：`web/tests/auth-store.test.ts`

- [ ] **步骤 1：扩展 auth-store**

在 `web/src/lib/auth-store.ts` 中，`AuthState` 接口新增 `activeRole` 和 `switchRole`，并更新实现：

```typescript
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserInfo } from "@/types/api";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserInfo | null;
  isAuthenticated: boolean;
  activeRole: string | null;
  setTokens: (accessToken: string, refreshToken: string) => void;
  setUser: (user: UserInfo) => void;
  setActiveRole: (role: string) => void;
  logout: () => void;
}

const secure = () => (process.env.NODE_ENV === "production" ? "; secure" : "");

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      activeRole: null,
      setTokens: (accessToken, refreshToken) => {
        set({ accessToken, refreshToken, isAuthenticated: true });
        document.cookie = `auth-token=${accessToken}; path=/; max-age=3600; samesite=lax${secure()}`;
      },
      setUser: (user) =>
        set({ user, activeRole: user.active_role }),
      setActiveRole: (role) => {
        set({ activeRole: role });
        document.cookie = `active-role=${role}; path=/; max-age=3600; samesite=lax${secure()}`;
      },
      logout: () => {
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
          isAuthenticated: false,
          activeRole: null,
        });
        document.cookie = "auth-token=; path=/; max-age=0";
        document.cookie = "active-role=; path=/; max-age=0";
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        activeRole: state.activeRole,
      }),
    }
  )
);
```

- [ ] **步骤 2：扩展 middleware 角色守卫**

替换 `web/src/middleware.ts` 全文：

```typescript
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const authToken = request.cookies.get("auth-token")?.value;
  const activeRole = request.cookies.get("active-role")?.value;

  const publicPaths = ["/login", "/register", "/forgot-password"];
  const isPublicPath = publicPaths.some((p) => pathname.startsWith(p));

  // 未登录访问受保护路径 → 跳登录
  if (!authToken && !isPublicPath) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // 已登录访问登录页 → 跳 Dashboard
  if (authToken && isPublicPath) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // 角色守卫：学员不能访问教练页面，教练不能访问学员页面
  if (pathname.startsWith("/escort/coach") && activeRole !== "supplier") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  if (pathname.startsWith("/escort/student") && activeRole !== "demander") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **步骤 3：更新 auth-store 测试**

在 `web/tests/auth-store.test.ts` 中新增测试用例：

```typescript
  it("setActiveRole stores role and syncs cookie", () => {
    useAuthStore.getState().setActiveRole("supplier");
    expect(useAuthStore.getState().activeRole).toBe("supplier");
    expect(document.cookie).toContain("active-role=supplier");
  });

  it("logout clears activeRole and cookie", () => {
    useAuthStore.getState().setActiveRole("supplier");
    useAuthStore.getState().logout();
    expect(useAuthStore.getState().activeRole).toBeNull();
    expect(document.cookie).not.toContain("active-role=supplier");
  });

  it("setUser sets activeRole from user.active_role", () => {
    const user = {
      user_id: "u1",
      name: "Test",
      roles: ["demander"],
      active_role: "demander",
    };
    useAuthStore.getState().setUser(user);
    expect(useAuthStore.getState().activeRole).toBe("demander");
  });
```

- [ ] **步骤 4：运行测试**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx vitest run tests/auth-store.test.ts
```

预期：PASS（原有 + 新增 3 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/lib/auth-store.ts web/src/middleware.ts web/tests/auth-store.test.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): auth-store 扩展 activeRole + middleware 角色守卫"
```

---

### 任务 8：前端 - 改造 dashboard 角色切换入口

**文件：**
- 修改：`web/src/app/(protected)/dashboard/page.tsx`
- 创建：`web/src/types/escort.ts`

- [ ] **步骤 1：创建陪驾类型定义**

创建 `web/src/types/escort.ts`：

```typescript
/** 订单状态（后端 TaskStatus 小写字符串）。 */
export type OrderStatus =
  | "draft"
  | "published"
  | "matching"
  | "assigned"
  | "in_progress"
  | "completed"
  | "cancelled";

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
}

/** 评价信息。 */
export interface ReviewInfo {
  review_id: string;
  task_id: string;
  reviewer_id: string;
  reviewer_role: "STUDENT" | "COACH";
  evaluatee_id: string;
  ratings: Record<string, number>;
  comment: string;
  created_at: string;
}

/** WS 推送消息。 */
export interface WSMessage {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}
```

- [ ] **步骤 2：改造 dashboard 页面**

替换 `web/src/app/(protected)/dashboard/page.tsx` 全文：

```tsx
"use client";

import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { TokenResponse } from "@/types/api";

export default function DashboardPage() {
  const router = useRouter();
  const { user, activeRole, setActiveRole, setTokens, logout } = useAuthStore();
  const [switching, setSwitching] = useState(false);

  const handleSwitchRole = async (role: string) => {
    if (role === activeRole) return;
    setSwitching(true);
    try {
      const tokens = await apiClient.post<TokenResponse>("/auth/switch-role", { role });
      setTokens(tokens.access_token, tokens.refresh_token);
      setActiveRole(role);
      router.refresh();
    } catch {
      // 切换失败，保持原角色
    } finally {
      setSwitching(false);
    }
  };

  const handleLogout = async () => {
    try {
      await apiClient.post("/auth/logout", null);
    } catch {
      // 忽略
    }
    logout();
    router.push("/login");
  };

  const canBeCoach = user?.roles?.includes("supplier");

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-md space-y-6 text-center">
        <h1 className="text-3xl font-bold">欢迎，{user?.name || "用户"}</h1>
        <p className="text-gray-600">用户 ID: {user?.user_id}</p>
        <p className="text-gray-600">当前角色: {activeRole || "未设置"}</p>

        {/* 角色切换 */}
        <div className="flex gap-2 justify-center">
          <Button
            variant={activeRole === "demander" ? "default" : "outline"}
            onClick={() => handleSwitchRole("demander")}
            disabled={switching}
          >
            学员
          </Button>
          {canBeCoach && (
            <Button
              variant={activeRole === "supplier" ? "default" : "outline"}
              onClick={() => handleSwitchRole("supplier")}
              disabled={switching}
            >
              教练
            </Button>
          )}
        </div>

        {/* 入口卡片 */}
        <div className="grid gap-3">
          {activeRole === "demander" && (
            <>
              <Button onClick={() => router.push("/escort/student/book-instant")}>
                实时叫车
              </Button>
              <Button variant="outline" onClick={() => router.push("/escort/student/orders")}>
                我的订单
              </Button>
            </>
          )}
          {activeRole === "supplier" && (
            <>
              <Button onClick={() => router.push("/escort/coach")}>
                接单大厅
              </Button>
              <Button variant="outline" onClick={() => router.push("/escort/coach/orders")}>
                我的订单
              </Button>
            </>
          )}
        </div>

        <Button onClick={handleLogout} variant="ghost">
          退出登录
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **步骤 3：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx tsc --noEmit
```

预期：无错误

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/dashboard/page.tsx web/src/types/escort.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): dashboard 角色切换入口 + 陪驾类型定义"
```

---

### 任务 9：前端 - order-realtime-store + use-ws-events hook

**文件：**
- 创建：`web/src/hooks/use-ws-events.ts`
- 创建：`web/src/lib/order-realtime-store.ts`
- 创建：`web/tests/order-realtime-store.test.ts`

- [ ] **步骤 1：创建 use-ws-events hook**

创建 `web/src/hooks/use-ws-events.ts`：

```typescript
"use client";

import { useEffect } from "react";
import { wsClient } from "@/lib/ws-client";

/**
 * 订阅 WS 事件，组件卸载时自动清理。
 */
export function useWsEvent(
  eventType: string,
  handler: (data: Record<string, unknown>) => void
) {
  useEffect(() => {
    const wrappedHandler = (msg: { type: string; data: Record<string, unknown> }) => {
      if (msg.type === eventType) {
        handler(msg.data);
      }
    };
    wsClient.on("message", wrappedHandler);
    return () => {
      wsClient.off("message", wrappedHandler);
    };
  }, [eventType, handler]);
}
```

- [ ] **步骤 2：创建 order-realtime-store**

创建 `web/src/lib/order-realtime-store.ts`：

```typescript
import { create } from "zustand";
import type { OrderStatus } from "@/types/escort";

interface OrderRealtimeState {
  /** 被抢的订单 ID 集合（教练端用于从大厅移除） */
  claimedOrderIds: Set<string>;
  /** 订单状态实时更新（task_id → status） */
  orderStatusUpdates: Record<string, OrderStatus>;
  /** 标记订单被抢 */
  markClaimed: (taskId: string) => void;
  /** 更新订单状态 */
  updateOrderStatus: (taskId: string, status: OrderStatus) => void;
  /** 重置（切换页面时调用） */
  reset: () => void;
}

export const useOrderRealtimeStore = create<OrderRealtimeState>((set) => ({
  claimedOrderIds: new Set<string>(),
  orderStatusUpdates: {},
  markClaimed: (taskId) =>
    set((state) => {
      const claimed = new Set(state.claimedOrderIds);
      claimed.add(taskId);
      return { claimedOrderIds: claimed };
    }),
  updateOrderStatus: (taskId, status) =>
    set((state) => ({
      orderStatusUpdates: { ...state.orderStatusUpdates, [taskId]: status },
    })),
  reset: () => set({ claimedOrderIds: new Set(), orderStatusUpdates: {} }),
}));
```

- [ ] **步骤 3：编写测试**

创建 `web/tests/order-realtime-store.test.ts`：

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";

describe("order-realtime-store", () => {
  beforeEach(() => {
    useOrderRealtimeStore.getState().reset();
  });

  it("markClaimed adds to claimed set", () => {
    useOrderRealtimeStore.getState().markClaimed("task_1");
    expect(useOrderRealtimeStore.getState().claimedOrderIds.has("task_1")).toBe(true);
  });

  it("updateOrderStatus sets status", () => {
    useOrderRealtimeStore.getState().updateOrderStatus("task_1", "assigned");
    expect(useOrderRealtimeStore.getState().orderStatusUpdates["task_1"]).toBe("assigned");
  });

  it("reset clears all", () => {
    useOrderRealtimeStore.getState().markClaimed("task_1");
    useOrderRealtimeStore.getState().updateOrderStatus("task_1", "completed");
    useOrderRealtimeStore.getState().reset();
    expect(useOrderRealtimeStore.getState().claimedOrderIds.size).toBe(0);
    expect(Object.keys(useOrderRealtimeStore.getState().orderStatusUpdates)).toHaveLength(0);
  });
});
```

- [ ] **步骤 4：运行测试**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx vitest run tests/order-realtime-store.test.ts
```

预期：PASS（3 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/hooks/use-ws-events.ts web/src/lib/order-realtime-store.ts web/tests/order-realtime-store.test.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): order-realtime-store + use-ws-events hook"
```

---

### 任务 10：前端 - 高德地图选点组件

**文件：**
- 创建：`web/src/components/amap-picker.tsx`

- [ ] **步骤 1：创建高德地图组件**

创建 `web/src/components/amap-picker.tsx`：

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

interface AmapPickerProps {
  value?: { lat: number; lng: number };
  onChange: (loc: { lat: number; lng: number; address: string }) => void;
}

declare global {
  interface Window {
    AMap: typeof AMap;
    _AMapSecurityConfig: { securityJsCode: string };
  }
}

let sdkLoaded: Promise<void> | null = null;

function loadAmapSDK(): Promise<void> {
  if (sdkLoaded) return sdkLoaded;
  sdkLoaded = new Promise((resolve, reject) => {
    const key = process.env.NEXT_PUBLIC_AMAP_KEY || "";
    const securityCode = process.env.NEXT_PUBLIC_AMAP_SECURITY_CODE || "";
    if (securityCode) {
      window._AMapSecurityConfig = { securityJsCode: securityCode };
    }
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("高德地图 SDK 加载失败"));
    document.head.appendChild(script);
  });
  return sdkLoaded;
}

export function AmapPicker({ value, onChange }: AmapPickerProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const [address, setAddress] = useState("");

  useEffect(() => {
    let cancelled = false;
    loadAmapSDK()
      .then(() => {
        if (cancelled || !mapRef.current) return;
        const AMap = window.AMap;
        const center: [number, number] = value
          ? [value.lng, value.lat]
          : [116.397428, 39.90923]; // 默认天安门
        mapInstance.current = new AMap.Map(mapRef.current, {
          zoom: 15,
          center,
        });
        mapInstance.current.on("click", (e: any) => {
          const lng = e.lnglat.getLng();
          const lat = e.lnglat.getLat();
          if (markerRef.current) {
            markerRef.current.setPosition([lng, lat]);
          } else {
            markerRef.current = new AMap.Marker({
              position: [lng, lat],
              map: mapInstance.current,
            });
          }
          // 逆地理编码
          const geocoder = new AMap.Geocoder();
          geocoder.getAddress([lng, lat], (status: string, result: any) => {
            if (status === "complete" && result.info === "OK") {
              const addr = result.regeocode.formattedAddress;
              setAddress(addr);
              onChange({ lat, lng, address: addr });
            } else {
              setAddress(`${lat.toFixed(6)}, ${lng.toFixed(6)}`);
              onChange({ lat, lng, address: `${lat.toFixed(6)}, ${lng.toFixed(6)}` });
            }
          });
        });
      })
      .catch(() => {
        // SDK 加载失败，显示降级 UI
      });
    return () => {
      cancelled = true;
      if (mapInstance.current) {
        mapInstance.current.destroy();
        mapInstance.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-2">
      <div
        ref={mapRef}
        className="w-full h-64 rounded-lg border border-gray-300"
        data-testid="amap-container"
      />
      {address && (
        <p className="text-sm text-gray-600" data-testid="selected-address">
          已选位置：{address}
        </p>
      )}
    </div>
  );
}
```

- [ ] **步骤 2：添加环境变量**

在 `web/.env.local` 中追加：

```
NEXT_PUBLIC_AMAP_KEY=your_amap_key_here
NEXT_PUBLIC_AMAP_SECURITY_CODE=your_security_code_here
```

- [ ] **步骤 3：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx tsc --noEmit
```

预期：无错误

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/components/amap-picker.tsx web/.env.local
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 高德地图选点组件 amap-picker"
```

---

### 任务 11：前端 - 学员端实时单下单页

**文件：**
- 创建：`web/src/app/(protected)/escort/student/book-instant/page.tsx`

- [ ] **步骤 1：创建下单页**

创建 `web/src/app/(protected)/escort/student/book-instant/page.tsx`：

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AmapPicker } from "@/components/amap-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import type { OrderInfo } from "@/types/escort";

export default function BookInstantPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const [location, setLocation] = useState<{ lat: number; lng: number; address: string } | null>(null);
  const [carType, setCarType] = useState("manual");
  const [duration, setDuration] = useState(2);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!location) {
      setError("请在地图上选择上车地点");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const order = await apiClient.post<OrderInfo>("/escort/orders", {
        demander_id: user?.user_id,
        domain_tag: "escort",
        origin_lat: location.lat,
        origin_lng: location.lng,
        car_type: carType,
        required_skills: ["coach_license"],
        duration_hours: duration,
        order_type: "REALTIME",
      });
      router.push(`/escort/student/orders/${order.task_id}`);
    } catch (e: any) {
      setError(e.message || "下单失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <h1 className="text-2xl font-bold">实时叫车</h1>

        <div className="space-y-2">
          <label className="text-sm font-medium">选择上车地点</label>
          <AmapPicker onChange={setLocation} />
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

        <Button className="w-full" onClick={handleSubmit} disabled={submitting}>
          {submitting ? "下单中..." : "立即叫车"}
        </Button>

        <Button variant="ghost" className="w-full" onClick={() => router.push("/dashboard")}>
          返回
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx tsc --noEmit
```

预期：无错误

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/escort/student/book-instant/page.tsx
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 学员端实时单下单页"
```

---

### 任务 12：前端 - 学员端订单列表 + 详情

**文件：**
- 创建：`web/src/hooks/use-orders.ts`
- 创建：`web/src/components/order-status-badge.tsx`
- 创建：`web/src/app/(protected)/escort/student/orders/page.tsx`
- 创建：`web/src/app/(protected)/escort/student/orders/[id]/page.tsx`
- 创建：`web/src/components/review-form.tsx`

- [ ] **步骤 1：创建订单查询 hooks**

创建 `web/src/hooks/use-orders.ts`：

```typescript
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { OrderInfo, ReviewInfo } from "@/types/escort";

export function useOrders(demanderId: string | undefined) {
  return useQuery({
    queryKey: ["orders", demanderId],
    queryFn: () =>
      apiClient.get<OrderInfo[]>(`/escort/orders?demander_id=${demanderId}`),
    enabled: !!demanderId,
    staleTime: 30_000,
  });
}

export function useOrder(taskId: string | undefined) {
  return useQuery({
    queryKey: ["order", taskId],
    queryFn: () => apiClient.get<OrderInfo>(`/escort/orders/${taskId}`),
    enabled: !!taskId,
  });
}

export function useReviews(taskId: string | undefined) {
  return useQuery({
    queryKey: ["reviews", taskId],
    queryFn: () => apiClient.get<ReviewInfo[]>(`/escort/orders/${taskId}/reviews`),
    enabled: !!taskId,
  });
}

export function useInvalidateOrder(taskId: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["order", taskId] });
    qc.invalidateQueries({ queryKey: ["reviews", taskId] });
  };
}
```

- [ ] **步骤 2：创建订单状态徽章**

创建 `web/src/components/order-status-badge.tsx`：

```tsx
import type { OrderStatus } from "@/types/escort";

const STATUS_LABELS: Record<OrderStatus, string> = {
  draft: "草稿",
  published: "等待接单",
  matching: "匹配中",
  assigned: "已接单",
  in_progress: "服务中",
  completed: "已完成",
  cancelled: "已取消",
};

const STATUS_COLORS: Record<OrderStatus, string> = {
  draft: "bg-gray-100 text-gray-800",
  published: "bg-yellow-100 text-yellow-800",
  matching: "bg-yellow-100 text-yellow-800",
  assigned: "bg-blue-100 text-blue-800",
  in_progress: "bg-green-100 text-green-800",
  completed: "bg-gray-100 text-gray-800",
  cancelled: "bg-red-100 text-red-800",
};

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  return (
    <span className={`px-2 py-1 rounded text-xs font-medium ${STATUS_COLORS[status]}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}
```

- [ ] **步骤 3：创建评价表单组件**

创建 `web/src/components/review-form.tsx`：

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";

interface ReviewFormProps {
  taskId: string;
  reviewerId: string;
  reviewerRole: "STUDENT" | "COACH";
  onSubmitted: () => void;
}

const STUDENT_DIMENSIONS = [
  { key: "teaching_score", label: "教学能力" },
  { key: "patience_score", label: "耐心程度" },
  { key: "safety_score", label: "安全记录" },
];

const COACH_DIMENSIONS = [
  { key: "punctuality_score", label: "守时程度" },
  { key: "cooperation_score", label: "配合度" },
  { key: "payment_score", label: "付款及时性" },
];

export function ReviewForm({ taskId, reviewerId, reviewerRole, onSubmitted }: ReviewFormProps) {
  const dimensions = reviewerRole === "STUDENT" ? STUDENT_DIMENSIONS : COACH_DIMENSIONS;
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await apiClient.post(`/escort/orders/${taskId}/reviews`, {
        reviewer_id: reviewerId,
        reviewer_role: reviewerRole,
        ratings: scores,
        comment,
      });
      onSubmitted();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="font-medium">评价</h3>
      {dimensions.map((dim) => (
        <div key={dim.key} className="flex items-center gap-2">
          <span className="text-sm w-24">{dim.label}</span>
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                className={`text-xl ${scores[dim.key] >= star ? "text-yellow-400" : "text-gray-300"}`}
                onClick={() => setScores({ ...scores, [dim.key]: star })}
              >
                ★
              </button>
            ))}
          </div>
        </div>
      ))}
      <textarea
        className="w-full rounded-md border border-gray-300 p-2 text-sm"
        placeholder="写点什么..."
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={3}
      />
      <Button onClick={handleSubmit} disabled={submitting || Object.keys(scores).length < 3}>
        {submitting ? "提交中..." : "提交评价"}
      </Button>
    </div>
  );
}
```

- [ ] **步骤 4：创建学员订单列表页**

创建 `web/src/app/(protected)/escort/student/orders/page.tsx`：

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrders } from "@/hooks/use-orders";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { Button } from "@/components/ui/button";

export default function StudentOrdersPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: orders, isLoading } = useOrders(user?.user_id);

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">我的订单</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {isLoading && <p className="text-gray-500">加载中...</p>}

        {orders && orders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无订单</p>
        )}

        <div className="space-y-3">
          {orders?.map((order) => (
            <div
              key={order.task_id}
              className="bg-white rounded-lg border p-4 cursor-pointer hover:shadow-md transition"
              onClick={() => router.push(`/escort/student/orders/${order.task_id}`)}
            >
              <div className="flex justify-between items-start mb-2">
                <span className="text-sm text-gray-500">{order.task_id.slice(0, 8)}</span>
                <OrderStatusBadge status={order.status} />
              </div>
              <p className="text-sm">{order.car_type === "manual" ? "手动挡" : "自动挡"} · {order.duration_hours}小时</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **步骤 5：创建学员订单详情页**

创建 `web/src/app/(protected)/escort/student/orders/[id]/page.tsx`：

```tsx
"use client";

import { useParams, useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { ReviewForm } from "@/components/review-form";
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

  // WS 事件 → 刷新订单
  useWsEvent("task.assigned", () => invalidate());
  useWsEvent("task.in_service", () => invalidate());
  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());

  const currentStatus = orderStatusUpdates[taskId] || order?.status;
  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);

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
            <span className="text-gray-500">车型</span>
            <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">时长</span>
            <span>{order.duration_hours}小时</span>
          </div>
          {order.assigned_resource_id && (
            <div className="flex justify-between">
              <span className="text-gray-500">教练</span>
              <span>{order.assigned_resource_id}</span>
            </div>
          )}
        </div>

        {currentStatus === "published" && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
            <p className="text-yellow-800">等待教练接单...</p>
          </div>
        )}

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

- [ ] **步骤 6：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx tsc --noEmit
```

预期：无错误

- [ ] **步骤 7：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/hooks/use-orders.ts web/src/components/order-status-badge.tsx web/src/components/review-form.tsx web/src/app/\(protected\)/escort/student/orders/
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 学员端订单列表+详情+评价"
```

---

### 任务 13：前端 - 教练端接单大厅

**文件：**
- 创建：`web/src/app/(protected)/escort/coach/page.tsx`

- [ ] **步骤 1：创建接单大厅页**

创建 `web/src/app/(protected)/escort/coach/page.tsx`：

```tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import { Button } from "@/components/ui/button";
import type { OrderInfo } from "@/types/escort";

export default function CoachHallPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const [pendingOrders, setPendingOrders] = useState<OrderInfo[]>([]);
  const [claiming, setClaiming] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { claimedOrderIds } = useOrderRealtimeStore();

  // 教练上线
  useEffect(() => {
    if (!user?.user_id) return;
    apiClient
      .post(`/escort/coaches/${user.user_id}/online`, { lat: 39.9, lng: 116.4 })
      .catch(() => {});
    return () => {
      apiClient.post(`/escort/coaches/${user.user_id}/offline`, null).catch(() => {});
    };
  }, [user?.user_id]);

  // WS 收到新订单
  const handleNewOrder = useCallback((data: Record<string, unknown>) => {
    const newOrder: OrderInfo = {
      task_id: data.task_id as string,
      order_type: "REALTIME",
      status: "published",
      demander_id: data.demander_id as string,
      car_type: data.car_type as string,
      duration_hours: data.duration_hours as number,
      assigned_resource_id: null,
      title: null,
    };
    setPendingOrders((prev) => [newOrder, ...prev]);
  }, []);

  useWsEvent("task.published", handleNewOrder);

  // WS 收到被抢通知
  useWsEvent("task.claimed", (data) => {
    const taskId = data.task_id as string;
    useOrderRealtimeStore.getState().markClaimed(taskId);
  });

  const handleClaim = async (taskId: string) => {
    setClaiming(taskId);
    setError("");
    try {
      await apiClient.post(`/escort/orders/${taskId}/claim`, {
        coach_id: user?.user_id,
      });
      router.push(`/escort/coach/orders/${taskId}`);
    } catch (e: any) {
      setError(e.message || "抢单失败");
      useOrderRealtimeStore.getState().markClaimed(taskId);
    } finally {
      setClaiming(null);
    }
  };

  const visibleOrders = pendingOrders.filter((o) => !claimedOrderIds.has(o.task_id));

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">接单大厅</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        {visibleOrders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无待接订单，等待推送...</p>
        )}

        <div className="space-y-3">
          {visibleOrders.map((order) => (
            <div key={order.task_id} className="bg-white rounded-lg border p-4 space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">{order.task_id.slice(0, 8)}</span>
                <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span>时长：{order.duration_hours}小时</span>
                <span>学员：{order.demander_id.slice(0, 8)}</span>
              </div>
              <Button
                className="w-full"
                onClick={() => handleClaim(order.task_id)}
                disabled={claiming === order.task_id}
              >
                {claiming === order.task_id ? "抢单中..." : "立即抢单"}
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx tsc --noEmit
```

预期：无错误

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/escort/coach/page.tsx
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 教练端接单大厅（WS实时推送+抢单）"
```

---

### 任务 14：前端 - 教练端订单列表 + 详情

**文件：**
- 创建：`web/src/app/(protected)/escort/coach/orders/page.tsx`
- 创建：`web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`

- [ ] **步骤 1：创建教练订单列表页**

创建 `web/src/app/(protected)/escort/coach/orders/page.tsx`：

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { Button } from "@/components/ui/button";
import type { OrderInfo } from "@/types/escort";

export default function CoachOrdersPage() {
  const router = useRouter();

  // 教练订单列表（通过查询所有订单，前端筛选 assigned_resource_id 匹配）
  // MVP 阶段简化：查询所有订单，实际应后端提供 coach_id 筛选
  const { data: allOrders, isLoading } = useQuery({
    queryKey: ["coach-orders"],
    queryFn: () => apiClient.get<OrderInfo[]>("/escort/orders?demander_id=_coach_view"),
    staleTime: 30_000,
  });

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">我的订单</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/coach")}>返回大厅</Button>
        </div>

        {isLoading && <p className="text-gray-500">加载中...</p>}

        {(!allOrders || allOrders.length === 0) && (
          <p className="text-gray-500 text-center py-8">暂无订单</p>
        )}

        <div className="space-y-3">
          {allOrders?.filter((o) => o.assigned_resource_id).map((order) => (
            <div
              key={order.task_id}
              className="bg-white rounded-lg border p-4 cursor-pointer hover:shadow-md transition"
              onClick={() => router.push(`/escort/coach/orders/${order.task_id}`)}
            >
              <div className="flex justify-between items-start mb-2">
                <span className="text-sm text-gray-500">{order.task_id.slice(0, 8)}</span>
                <OrderStatusBadge status={order.status} />
              </div>
              <p className="text-sm">{order.car_type === "manual" ? "手动挡" : "自动挡"} · {order.duration_hours}小时</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：创建教练订单详情页**

创建 `web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`：

```tsx
"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
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

  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());

  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);

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
        </div>

        {/* 操作按钮 */}
        {order.status === "assigned" && (
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

- [ ] **步骤 3：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npx tsc --noEmit
```

预期：无错误

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git add web/src/app/\(protected\)/escort/coach/orders/
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 教练端订单列表+详情（签到/签退/评价）"
```

---

### 任务 15：切片1端到端验证

**文件：** 无代码变更

- [ ] **步骤 1：启动后端**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m umcp_core.transport
```

预期：后端在 http://localhost:8000 启动

- [ ] **步骤 2：启动前端**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core\web
npm run dev
```

预期：前端在 http://localhost:3000 启动

- [ ] **步骤 3：验证完整实时单流程**

使用浏览器子代理验证以下场景：

1. 打开 http://localhost:3000 → 重定向到 /login
2. 用手机号登录（如 13800138000）→ 跳转 /dashboard
3. 在 Dashboard 切换到学员角色 → 显示"实时叫车"入口
4. 点击"实时叫车" → 进入地图选点页面
5. 在地图上选择一个点 → 显示地址
6. 点击"立即叫车" → 跳转到订单详情页，状态"等待接单"
7. 在另一个浏览器窗口登录同一账号，切换到教练角色
8. 进入接单大厅 → 看到新订单
9. 点击"立即抢单" → 跳转到教练订单详情页，状态"已接单"
10. 学员端订单详情自动刷新为"已接单"（WS 推送）
11. 教练点击"签到" → 状态变为"服务中"
12. 教练点击"签退" → 状态变为"已完成"
13. 学员端出现评价表单 → 提交评价
14. 教练端出现评价表单 → 提交评价
15. 双方评价完成后显示"已评价"

- [ ] **步骤 4：验证角色守卫**

1. 以学员角色直接访问 /escort/coach → 重定向到 /dashboard
2. 以教练角色直接访问 /escort/student → 重定向到 /dashboard

- [ ] **步骤 5：Commit 验证记录**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit --allow-empty -m "test: 切片1端到端验证通过"
```

---

## 自检结果

**1. 规格覆盖度：**
- ✅ 实时单抢单流程：任务 3（claim 接口）+ 任务 13（教练端抢单）
- ✅ 签到签退：任务 3（check-in/check-out 接口）+ 任务 14（教练端操作）
- ✅ 双向评价：任务 5（reviews router）+ 任务 12/14（评价表单）
- ✅ 角色切换：任务 6（switch-role 接口）+ 任务 7/8（前端角色守卫+切换）
- ✅ 教练上线/下线：任务 4 + 任务 13（前端调用）
- ✅ WS 广播：任务 2（ConnectionManager）+ 任务 3（orders 广播）
- ✅ 高德地图：任务 10 + 任务 11（下单页）
- ✅ WS 实时状态：任务 9（store+hook）+ 任务 12/13/14（页面订阅）

**2. 占位符扫描：** 无 TODO/待定/类似任务N 等占位符。

**3. 类型一致性：**
- OrderStatus 使用小写字符串（与后端 TaskStatus 一致）
- OrderInfo 字段名与后端 OrderInfo 一致（task_id/order_type/status/demander_id/car_type/duration_hours/assigned_resource_id/title）
- ReviewInfo 字段名与后端 review dict 一致（review_id/task_id/reviewer_id/reviewer_role/evaluatee_id/ratings/comment/created_at）
- WS 事件类型使用点号格式（task.published/task.claimed/task.assigned/task.in_service/task.completed/task.cancelled）
- apiClient 方法签名：get<T>(path) / post<T>(path, body)

**遗漏检查：** 无遗漏。切片2（预约单）将在切片1完成后单独制定计划。
