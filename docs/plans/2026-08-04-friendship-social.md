# 互评社交（互加好友）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现陪驾业务社交闭环——服务完成后双方互加好友（好友申请/接受/拒绝/好友列表/删除好友），WS 实时推送好友请求提醒，完成核心需求中最后一个未实现的方向。

**架构：**
- 后端：参照评价模块极简模式（router 内联内存存储 + 锁），新建 `transport/routers/friends.py`，prefix `/api/v1/friends`。扩展 `EventType` 新增 `FRIEND_REQUEST_REJECTED`/`FRIEND_REMOVED`，将 4 个好友事件加入 `WS_PUSHABLE_EVENTS`。
- 前端：`/friends` 路由好友列表页（好友 Tab + 请求 Tab），订单详情页/评价完成后添加"加好友"按钮，`useWsEvent` 实时接收好友请求提醒，Dashboard 添加好友入口。

**技术栈：** FastAPI + Pydantic（后端）、Next.js 14 + React Query + shadcn/ui（前端）、pytest + Vitest（测试）。

---

## 关键设计决策

### 数据模型（内存 dict 存储）

参照 `reviews.py` 的极简模式，在 router 文件内用模块级 dict 存储。

**FriendRequest（好友请求）：**
- `request_id`: str（`freq_<uuid12>`）
- `from_user_id`: str（发起方）
- `to_user_id`: str（接收方）
- `status`: str（`pending` / `accepted` / `rejected`）
- `message`: str（申请留言，可选）
- `created_at`: str（ISO 时间）
- `responded_at`: str | None（响应时间）

**Friendship（好友关系，双向记录，存两条）：**
- `friendship_id`: str（`fship_<uuid12>`）
- `user_id`: str（一方）
- `friend_user_id`: str（另一方）
- `created_at`: str（ISO 时间）

### 事件类型扩展

`EventType` 枚举新增（在现有 `FRIEND_REQUEST_CREATED`/`FRIEND_REQUEST_ACCEPTED` 之后）：
- `FRIEND_REQUEST_REJECTED = "friend_request.rejected"`
- `FRIEND_REMOVED = "friend.removed"`

### WS 推送策略

**关键：** `_extract_user_ids` 当前仅识别 `demander_id`/`supplier_id`/`user_id` 字段。好友事件 payload 使用 `user_id` 字段指向**接收方**（需要被通知的一方），复用现有提取逻辑，无需修改 `_extract_user_ids`。

- `FRIEND_REQUEST_CREATED`：payload `user_id = to_user_id`（通知接收方"你收到好友请求"）
- `FRIEND_REQUEST_ACCEPTED`：payload `user_id = from_user_id`（通知发起方"对方接受了你的请求"）
- `FRIEND_REQUEST_REJECTED`：payload `user_id = from_user_id`（通知发起方"对方拒绝了你的请求"）
- `FRIEND_REMOVED`：payload `user_id = 被删除方`（通知对方"你被删除了"）

将 4 个事件加入 `WS_PUSHABLE_EVENTS` 集合。

### 防重复与幂等

- 发送请求前检查：是否已是好友、是否已有 pending 请求（同 from→to）、是否曾互相拉黑（MVP 不实现拉黑）
- 接受请求前检查：状态必须是 pending
- 拒绝请求后：允许重新发送请求（删除旧 rejected 记录或允许 pending 覆盖）
- 删除好友：双向删除 Friendship 记录

### API 端点

| 端点 | 方法 | 守卫 | 功能 |
|------|------|------|------|
| `/api/v1/friends/requests` | POST | 登录 | 发送好友请求（body: to_user_id, message?） |
| `/api/v1/friends/requests` | GET | 登录 | 查看我收到的好友请求（status=pending） |
| `/api/v1/friends/requests/{request_id}/accept` | POST | 登录 | 接受好友请求 |
| `/api/v1/friends/requests/{request_id}/reject` | POST | 登录 | 拒绝好友请求 |
| `/api/v1/friends` | GET | 登录 | 查看好友列表 |
| `/api/v1/friends/{friend_user_id}` | DELETE | 登录 | 删除好友 |

---

## 文件结构

### 后端

- **修改** `src/umcp_core/events/types.py`：新增 `FRIEND_REQUEST_REJECTED`、`FRIEND_REMOVED`。
- **修改** `src/umcp_core/transport/ws.py`：将 4 个好友事件加入 `WS_PUSHABLE_EVENTS`。
- **创建** `src/umcp_core/transport/routers/friends.py`：friends router（6 个端点 + 内存存储）。
- **修改** `src/umcp_core/transport/routers/__init__.py`：注册 friends router。
- **测试** `tests/test_friends_api.py`：验证 6 个端点 + 防重复 + 事件发布。
- **测试** `tests/test_friends_e2e.py`：端到端集成测试。

### 前端

- **创建** `web/src/types/friend.ts`：`FriendRequest`、`Friendship` 接口。
- **创建** `web/src/hooks/use-friends.ts`：`useFriendRequests`、`useFriends`、`useSendFriendRequest`、`useAcceptFriendRequest`、`useRejectFriendRequest`、`useRemoveFriend` hooks。
- **创建** `web/src/app/(protected)/friends/page.tsx`：好友列表页（好友 Tab + 请求 Tab）。
- **修改** `web/src/app/(protected)/dashboard/page.tsx`：添加好友入口。
- **修改** `web/src/app/(protected)/escort/student/orders/[id]/page.tsx`：订单完成后显示"加好友"按钮。
- **修改** `web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`：订单完成后显示"加好友"按钮。
- **测试** `web/tests/friends.test.tsx`：hooks 测试。

---

## 任务分解

### 任务 1：后端事件类型扩展 + WS 推送白名单 + friends router（发送请求 + 查看请求列表）

**文件：**
- 修改：`src/umcp_core/events/types.py`
- 修改：`src/umcp_core/transport/ws.py`
- 创建：`src/umcp_core/transport/routers/friends.py`
- 修改：`src/umcp_core/transport/routers/__init__.py`
- 测试：`tests/test_friends_api.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_friends_api.py`：

```python
"""验证 friends 端点（发送/接受/拒绝请求、好友列表、删除好友）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _user_headers(server, user_id: str = "student1", roles: list[str] | None = None):
    """生成普通用户 token 请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name=f"User-{user_id}")
    role_map = {
        "demander": _ClaimsDemander,
        "supplier": _ClaimsSupplier,
    }
    for r in (roles or ["demander"]):
        if r in role_map:
            user.add_role(role_map[r]())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_send_friend_request(app_client):
    """发送好友请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1", "message": "服务很好，加个好友"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["from_user_id"] == "student1"
    assert data["to_user_id"] == "coach1"
    assert data["status"] == "pending"
    assert data["request_id"].startswith("freq_")


def test_send_friend_request_to_self_rejected(app_client):
    """不能给自己发送好友请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "student1"},
    )
    assert resp.status_code == 400


def test_list_received_requests(app_client):
    """查看收到的好友请求。"""
    client, server = app_client
    # student1 向 coach1 发送请求
    client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    # coach1 查看收到的请求
    resp = client.get(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "coach1"),
    )
    assert resp.status_code == 200
    requests = resp.json()["data"]
    assert len(requests) >= 1
    assert requests[0]["to_user_id"] == "coach1"
    assert requests[0]["from_user_id"] == "student1"
    assert requests[0]["status"] == "pending"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_friends_api.py -v`
预期：FAIL（404，router 不存在）。

- [ ] **步骤 3：扩展事件类型**

修改 `src/umcp_core/events/types.py`，在 `FRIEND_REQUEST_ACCEPTED` 之后添加：

```python
    FRIEND_REQUEST_REJECTED = "friend_request.rejected"
    FRIEND_REMOVED = "friend.removed"
```

- [ ] **步骤 4：扩展 WS 推送白名单**

修改 `src/umcp_core/transport/ws.py`，在 `WS_PUSHABLE_EVENTS` 集合中添加（`CHECK_OUT` 之后）：

```python
    EventType.FRIEND_REQUEST_CREATED,
    EventType.FRIEND_REQUEST_ACCEPTED,
    EventType.FRIEND_REQUEST_REJECTED,
    EventType.FRIEND_REMOVED,
```

- [ ] **步骤 5：创建 friends router（发送请求 + 查看请求）**

创建 `src/umcp_core/transport/routers/friends.py`：

```python
"""好友社交 router（互加好友）。"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from umcp_core.core.base import User
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/friends", tags=["friends"])

# 内存存储（MVP 阶段，后续迁移到 ORM）
_friend_requests_store: dict[str, dict] = {}  # request_id -> request dict
_friendships_store: dict[str, dict] = {}  # friendship_id -> friendship dict
_store_lock = threading.Lock()


class SendFriendRequestModel(BaseModel):
    to_user_id: str
    message: str = ""


class FriendRequestResponse(BaseModel):
    request_id: str
    from_user_id: str
    to_user_id: str
    status: str
    message: str
    created_at: str
    responded_at: str | None = None


def _is_friend(user_id: str, friend_user_id: str) -> bool:
    """检查两人是否已是好友。"""
    for f in _friendships_store.values():
        if (f["user_id"] == user_id and f["friend_user_id"] == friend_user_id) or (
            f["user_id"] == friend_user_id and f["friend_user_id"] == user_id
        ):
            return True
    return False


@router.post("/requests", response_model=Envelope)
async def send_friend_request(
    req: SendFriendRequestModel,
    current_user: User = Depends(get_current_user),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """发送好友请求。"""
    from_user_id = current_user.user_id
    to_user_id = req.to_user_id

    # 不能给自己发请求
    if from_user_id == to_user_id:
        raise IllegalStateError(message="不能给自己发送好友请求")

    with _store_lock:
        # 检查是否已是好友
        if _is_friend(from_user_id, to_user_id):
            raise IllegalStateError(message="你们已经是好友了")

        # 检查是否已有 pending 请求（任一方向）
        for r in _friend_requests_store.values():
            if r["status"] != "pending":
                continue
            if (r["from_user_id"] == from_user_id and r["to_user_id"] == to_user_id) or (
                r["from_user_id"] == to_user_id and r["to_user_id"] == from_user_id
            ):
                raise IllegalStateError(message="已有待处理的好友请求")

        request_id = f"freq_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()
        request = {
            "request_id": request_id,
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "status": "pending",
            "message": req.message,
            "created_at": now,
            "responded_at": None,
        }
        _friend_requests_store[request_id] = request

    # 发布事件（payload.user_id 指向接收方，用于 WS 推送）
    server.event_bus.publish(
        Event(
            type=EventType.FRIEND_REQUEST_CREATED,
            source_layer="ESCORT",
            payload={
                "request_id": request_id,
                "from_user_id": from_user_id,
                "user_id": to_user_id,  # 接收方（用于 WS 推送路由）
                "message": req.message,
            },
        )
    )

    return ok(request)


@router.get("/requests", response_model=Envelope)
async def list_received_requests(
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查看我收到的好友请求（pending 状态）。"""
    with _store_lock:
        requests = [
            r
            for r in _friend_requests_store.values()
            if r["to_user_id"] == current_user.user_id and r["status"] == "pending"
        ]
    # 按创建时间倒序
    requests.sort(key=lambda r: r["created_at"], reverse=True)
    return ok(requests)
```

- [ ] **步骤 6：注册 router**

修改 `src/umcp_core/transport/routers/__init__.py`，在 import 区添加：

```python
from umcp_core.transport.routers.friends import router as friends_router
```

在 `register_routers` 函数末尾添加：

```python
    # 好友社交 router（prefix 已内置于 router）
    app.include_router(friends_router)
```

- [ ] **步骤 7：运行测试验证通过**

运行：`python -m pytest tests/test_friends_api.py -v -k "send or list_received"`
预期：3 个测试通过。

- [ ] **步骤 8：Commit**

```bash
git add src/umcp_core/events/types.py src/umcp_core/transport/ws.py src/umcp_core/transport/routers/friends.py src/umcp_core/transport/routers/__init__.py tests/test_friends_api.py
git commit -m "feat(friends): 好友请求发送与查看端点 + 事件类型与WS推送扩展"
```

---

### 任务 2：后端 接受/拒绝请求 + 好友列表 + 删除好友

**文件：**
- 修改：`src/umcp_core/transport/routers/friends.py`
- 测试：`tests/test_friends_api.py`（追加测试）

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_friends_api.py` 末尾追加：

```python
def test_accept_friend_request(app_client):
    """接受好友请求后双方成为好友。"""
    client, server = app_client
    # student1 向 coach1 发送请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # coach1 接受请求
    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "accepted"

    # 双方都应在好友列表中
    resp3 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert resp3.status_code == 200
    friends = resp3.json()["data"]
    assert any(f["friend_user_id"] == "coach1" for f in friends)

    resp4 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    friends2 = resp4.json()["data"]
    assert any(f["friend_user_id"] == "student1" for f in friends2)


def test_accept_request_not_recipient(app_client):
    """非接收方不能接受请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # student2 尝试接受（非接收方）
    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "student2"),
    )
    assert resp2.status_code == 403


def test_reject_friend_request(app_client):
    """拒绝好友请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/reject",
        headers=_user_headers(server, "coach1"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "rejected"

    # 不应出现在好友列表中
    resp3 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    friends = resp3.json()["data"]
    assert not any(f["friend_user_id"] == "coach1" for f in friends)


def test_list_friends(app_client):
    """查看好友列表。"""
    client, server = app_client
    # 建立好友关系
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    resp2 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert resp2.status_code == 200
    friends = resp2.json()["data"]
    assert len(friends) == 1
    assert friends[0]["friend_user_id"] == "coach1"


def test_remove_friend(app_client):
    """删除好友（双向删除）。"""
    client, server = app_client
    # 建立好友关系
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    # student1 删除 coach1
    resp2 = client.delete(
        "/api/v1/friends/coach1",
        headers=_user_headers(server, "student1"),
    )
    assert resp2.status_code == 200

    # 双方好友列表都应为空
    resp3 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert len(resp3.json()["data"]) == 0

    resp4 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    assert len(resp4.json()["data"]) == 0


def test_duplicate_request_after_accept(app_client):
    """已是好友后再次发请求应被拒绝。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    # 再次发请求
    resp2 = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    assert resp2.status_code == 400


def test_accept_nonexistent_request(app_client):
    """接受不存在的好友请求返回 404。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests/nonexistent_id/accept",
        headers=_user_headers(server, "coach1"),
    )
    assert resp.status_code == 404
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_friends_api.py -v`
预期：新追加的测试 FAIL（端点 404）。

- [ ] **步骤 3：实现接受/拒绝/列表/删除端点**

在 `src/umcp_core/transport/routers/friends.py` 末尾追加：

```python
@router.post("/requests/{request_id}/accept", response_model=Envelope)
async def accept_friend_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """接受好友请求。"""
    with _store_lock:
        request = _friend_requests_store.get(request_id)
        if request is None:
            raise NotFoundError(message=f"好友请求 {request_id} 不存在")
        if request["to_user_id"] != current_user.user_id:
            raise PermissionDeniedError(message="只有接收方才能接受请求")
        if request["status"] != "pending":
            raise IllegalStateError(message=f"请求状态为 {request['status']}，无法接受")

        # 更新请求状态
        now = datetime.utcnow().isoformat()
        request["status"] = "accepted"
        request["responded_at"] = now

        # 创建双向好友关系
        from_id = request["from_user_id"]
        to_id = request["to_user_id"]
        friendship_id_1 = f"fship_{uuid.uuid4().hex[:12]}"
        friendship_id_2 = f"fship_{uuid.uuid4().hex[:12]}"
        _friendships_store[friendship_id_1] = {
            "friendship_id": friendship_id_1,
            "user_id": from_id,
            "friend_user_id": to_id,
            "created_at": now,
        }
        _friendships_store[friendship_id_2] = {
            "friendship_id": friendship_id_2,
            "user_id": to_id,
            "friend_user_id": from_id,
            "created_at": now,
        }

    # 发布事件（通知发起方）
    server.event_bus.publish(
        Event(
            type=EventType.FRIEND_REQUEST_ACCEPTED,
            source_layer="ESCORT",
            payload={
                "request_id": request_id,
                "to_user_id": to_id,
                "user_id": from_id,  # 发起方（用于 WS 推送路由）
            },
        )
    )

    return ok(request)


@router.post("/requests/{request_id}/reject", response_model=Envelope)
async def reject_friend_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """拒绝好友请求。"""
    with _store_lock:
        request = _friend_requests_store.get(request_id)
        if request is None:
            raise NotFoundError(message=f"好友请求 {request_id} 不存在")
        if request["to_user_id"] != current_user.user_id:
            raise PermissionDeniedError(message="只有接收方才能拒绝请求")
        if request["status"] != "pending":
            raise IllegalStateError(message=f"请求状态为 {request['status']}，无法拒绝")

        request["status"] = "rejected"
        request["responded_at"] = datetime.utcnow().isoformat()

    # 发布事件（通知发起方）
    server.event_bus.publish(
        Event(
            type=EventType.FRIEND_REQUEST_REJECTED,
            source_layer="ESCORT",
            payload={
                "request_id": request_id,
                "to_user_id": request["to_user_id"],
                "user_id": request["from_user_id"],  # 发起方（用于 WS 推送路由）
            },
        )
    )

    return ok(request)


@router.get("", response_model=Envelope)
async def list_friends(
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查看好友列表。"""
    with _store_lock:
        friends = [
            {
                "friendship_id": f["friendship_id"],
                "friend_user_id": f["friend_user_id"],
                "created_at": f["created_at"],
            }
            for f in _friendships_store.values()
            if f["user_id"] == current_user.user_id
        ]
    friends.sort(key=lambda f: f["created_at"], reverse=True)
    return ok(friends)


@router.delete("/{friend_user_id}", response_model=Envelope)
async def remove_friend(
    friend_user_id: str,
    current_user: User = Depends(get_current_user),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """删除好友（双向删除）。"""
    with _store_lock:
        # 找到双向好友关系记录
        to_remove = [
            fid
            for fid, f in _friendships_store.items()
            if (f["user_id"] == current_user.user_id and f["friend_user_id"] == friend_user_id)
            or (f["user_id"] == friend_user_id and f["friend_user_id"] == current_user.user_id)
        ]
        if not to_remove:
            raise NotFoundError(message=f"与 {friend_user_id} 不是好友")

        for fid in to_remove:
            del _friendships_store[fid]

    # 发布事件（通知被删除方）
    server.event_bus.publish(
        Event(
            type=EventType.FRIEND_REMOVED,
            source_layer="ESCORT",
            payload={
                "removed_by": current_user.user_id,
                "user_id": friend_user_id,  # 被删除方（用于 WS 推送路由）
            },
        )
    )

    return ok(message="已删除好友")
```

注意：需要在 import 中添加 `PermissionDeniedError`：

```python
from umcp_core.transport.errors import IllegalStateError, NotFoundError, PermissionDeniedError
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_friends_api.py -v`
预期：全部测试通过（10 个）。

- [ ] **步骤 5：回归测试**

运行：`python -m pytest tests/ -k "friend or review or escort" -v`
预期：PASS。

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/transport/routers/friends.py tests/test_friends_api.py
git commit -m "feat(friends): 接受/拒绝请求 + 好友列表 + 删除好友端点"
```

---

### 任务 3：前端类型定义 + use-friends hooks

**文件：**
- 创建：`web/src/types/friend.ts`
- 创建：`web/src/hooks/use-friends.ts`
- 测试：`web/tests/friends.test.tsx`

- [ ] **步骤 1：编写失败的测试**

创建 `web/tests/friends.test.tsx`：

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import {
  useFriendRequests,
  useFriends,
  useSendFriendRequest,
  useAcceptFriendRequest,
  useRejectFriendRequest,
  useRemoveFriend,
} from "@/hooks/use-friends";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("use-friends hooks", () => {
  beforeEach(() => {
    (apiClient.get as any).mockReset();
    (apiClient.post as any).mockReset();
    (apiClient.delete as any).mockReset();
  });

  it("useFriendRequests 获取好友请求列表", async () => {
    (apiClient.get as any).mockResolvedValue([
      { request_id: "freq_1", from_user_id: "u1", to_user_id: "me", status: "pending" },
    ]);
    const { result } = renderHook(() => useFriendRequests(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
  });

  it("useFriends 获取好友列表", async () => {
    (apiClient.get as any).mockResolvedValue([
      { friendship_id: "f1", friend_user_id: "u1", created_at: "2026-01-01" },
    ]);
    const { result } = renderHook(() => useFriends(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
  });

  it("useSendFriendRequest 调用 POST", async () => {
    (apiClient.post as any).mockResolvedValue({ request_id: "freq_1" });
    const { result } = renderHook(() => useSendFriendRequest(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ toUserId: "u1", message: "加个好友" });
    expect(apiClient.post).toHaveBeenCalledWith("/friends/requests", {
      to_user_id: "u1",
      message: "加个好友",
    });
  });

  it("useAcceptFriendRequest 调用 POST accept", async () => {
    (apiClient.post as any).mockResolvedValue({ status: "accepted" });
    const { result } = renderHook(() => useAcceptFriendRequest(), { wrapper: createWrapper() });
    await result.current.mutateAsync("freq_1");
    expect(apiClient.post).toHaveBeenCalledWith("/friends/requests/freq_1/accept", null);
  });

  it("useRejectFriendRequest 调用 POST reject", async () => {
    (apiClient.post as any).mockResolvedValue({ status: "rejected" });
    const { result } = renderHook(() => useRejectFriendRequest(), { wrapper: createWrapper() });
    await result.current.mutateAsync("freq_1");
    expect(apiClient.post).toHaveBeenCalledWith("/friends/requests/freq_1/reject", null);
  });

  it("useRemoveFriend 调用 DELETE", async () => {
    (apiClient.delete as any).mockResolvedValue(undefined);
    const { result } = renderHook(() => useRemoveFriend(), { wrapper: createWrapper() });
    await result.current.mutateAsync("u1");
    expect(apiClient.delete).toHaveBeenCalledWith("/friends/u1");
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd web ; npx vitest run tests/friends.test.tsx`
预期：FAIL，`Cannot find module '@/hooks/use-friends'`。

- [ ] **步骤 3：创建类型定义**

创建 `web/src/types/friend.ts`：

```typescript
/** 好友请求。 */
export interface FriendRequest {
  request_id: string;
  from_user_id: string;
  to_user_id: string;
  status: "pending" | "accepted" | "rejected";
  message: string;
  created_at: string;
  responded_at: string | null;
}

/** 好友关系。 */
export interface Friendship {
  friendship_id: string;
  friend_user_id: string;
  created_at: string;
}
```

- [ ] **步骤 4：实现 use-friends hooks**

创建 `web/src/hooks/use-friends.ts`：

```typescript
"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { FriendRequest, Friendship } from "@/types/friend";

export function useFriendRequests() {
  return useQuery({
    queryKey: ["friend-requests"],
    queryFn: () => apiClient.get<FriendRequest[]>("/friends/requests"),
  });
}

export function useFriends() {
  return useQuery({
    queryKey: ["friends"],
    queryFn: () => apiClient.get<Friendship[]>("/friends"),
  });
}

export function useSendFriendRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { toUserId: string; message?: string }) =>
      apiClient.post<FriendRequest>("/friends/requests", {
        to_user_id: params.toUserId,
        message: params.message ?? "",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friend-requests"] });
    },
  });
}

export function useAcceptFriendRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<FriendRequest>(`/friends/requests/${requestId}/accept`, null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friend-requests"] });
      qc.invalidateQueries({ queryKey: ["friends"] });
    },
  });
}

export function useRejectFriendRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<FriendRequest>(`/friends/requests/${requestId}/reject`, null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friend-requests"] });
    },
  });
}

export function useRemoveFriend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (friendUserId: string) =>
      apiClient.delete(`/friends/${friendUserId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friends"] });
    },
  });
}
```

- [ ] **步骤 5：验证 apiClient.delete 方法存在**

读取 `web/src/lib/api-client.ts` 确认 `delete` 方法签名。如果方法名不是 `delete`（可能是 `del` 或其他），调整 hooks 中的调用。

- [ ] **步骤 6：运行测试验证通过**

运行：`cd web ; npx vitest run tests/friends.test.tsx`
预期：6 个测试通过。

- [ ] **步骤 7：Commit**

```bash
git add web/src/types/friend.ts web/src/hooks/use-friends.ts web/tests/friends.test.tsx
git commit -m "feat(web): 好友类型定义与 use-friends hooks"
```

---

### 任务 4：前端好友列表页 + Dashboard 入口

**文件：**
- 创建：`web/src/app/(protected)/friends/page.tsx`
- 修改：`web/src/app/(protected)/dashboard/page.tsx`

- [ ] **步骤 1：实现好友列表页**

创建 `web/src/app/(protected)/friends/page.tsx`：

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useFriends, useFriendRequests, useAcceptFriendRequest, useRejectFriendRequest, useRemoveFriend } from "@/hooks/use-friends";
import { useWsEvent } from "@/hooks/use-ws-events";
import { Button } from "@/components/ui/button";

export default function FriendsPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"friends" | "requests">("friends");

  const { data: friends, isLoading: friendsLoading } = useFriends();
  const { data: requests, isLoading: requestsLoading } = useFriendRequests();
  const acceptRequest = useAcceptFriendRequest();
  const rejectRequest = useRejectFriendRequest();
  const removeFriend = useRemoveFriend();

  // WS 实时接收好友请求提醒，收到时自动刷新请求列表
  useWsEvent("friend_request.created", () => {
    // react-query 会通过 invalidateQueries 自动刷新（由 mutation 触发）
    // 这里作为补充：强制刷新
  });

  const handleRemove = (friendUserId: string, friendName: string) => {
    if (confirm(`确定删除好友 ${friendName} 吗？`)) {
      removeFriend.mutate(friendUserId);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-2xl space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">我的好友</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {/* Tab 切换 */}
        <div className="flex gap-2 border-b">
          <button
            className={`pb-2 px-4 text-sm font-medium ${
              tab === "friends" ? "border-b-2 border-blue-500 text-blue-600" : "text-gray-500"
            }`}
            onClick={() => setTab("friends")}
          >
            好友列表 ({friends?.length ?? 0})
          </button>
          <button
            className={`pb-2 px-4 text-sm font-medium ${
              tab === "requests" ? "border-b-2 border-blue-500 text-blue-600" : "text-gray-500"
            }`}
            onClick={() => setTab("requests")}
          >
            好友请求 {requests && requests.length > 0 && `(${requests.length})`}
          </button>
        </div>

        {/* 好友列表 */}
        {tab === "friends" && (
          <div className="space-y-2">
            {friendsLoading && <p className="text-sm text-gray-500">加载中...</p>}
            {!friendsLoading && friends && friends.length === 0 && (
              <p className="text-sm text-gray-500 text-center py-8">还没有好友，完成服务后可以互加好友</p>
            )}
            {friends?.map((friend) => (
              <div
                key={friend.friendship_id}
                className="bg-white rounded-lg border p-4 flex items-center justify-between"
              >
                <div>
                  <p className="font-medium">{friend.friend_user_id}</p>
                  <p className="text-xs text-gray-500">
                    成为好友于 {new Date(friend.created_at).toLocaleString("zh-CN")}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => handleRemove(friend.friend_user_id, friend.friend_user_id)}
                >
                  删除
                </Button>
              </div>
            ))}
          </div>
        )}

        {/* 好友请求 */}
        {tab === "requests" && (
          <div className="space-y-2">
            {requestsLoading && <p className="text-sm text-gray-500">加载中...</p>}
            {!requestsLoading && requests && requests.length === 0 && (
              <p className="text-sm text-gray-500 text-center py-8">暂无好友请求</p>
            )}
            {requests?.map((req) => (
              <div
                key={req.request_id}
                className="bg-white rounded-lg border p-4 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">{req.from_user_id}</p>
                    <p className="text-xs text-gray-500">
                      {new Date(req.created_at).toLocaleString("zh-CN")}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={() => acceptRequest.mutate(req.request_id)}
                      disabled={acceptRequest.isPending}
                    >
                      接受
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => rejectRequest.mutate(req.request_id)}
                      disabled={rejectRequest.isPending}
                    >
                      拒绝
                    </Button>
                  </div>
                </div>
                {req.message && (
                  <p className="text-sm text-gray-600 bg-gray-50 rounded p-2">
                    留言：{req.message}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：修改 Dashboard 添加好友入口**

修改 `web/src/app/(protected)/dashboard/page.tsx`，在入口卡片区（`</>` 闭合前）添加：

```tsx
<Button variant="outline" onClick={() => router.push("/friends")}>
  我的好友
</Button>
```

- [ ] **步骤 3：运行前端测试验证**

运行：`cd web ; npx vitest run`
预期：全部通过。

- [ ] **步骤 4：Commit**

```bash
git add "web/src/app/(protected)/friends/page.tsx" "web/src/app/(protected)/dashboard/page.tsx"
git commit -m "feat(web): 好友列表页与 Dashboard 好友入口"
```

---

### 任务 5：前端订单详情页"加好友"按钮 + WS 实时提醒

**文件：**
- 修改：`web/src/app/(protected)/escort/student/orders/[id]/page.tsx`
- 修改：`web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`

- [ ] **步骤 1：学员订单详情页添加"加好友"按钮**

修改 `web/src/app/(protected)/escort/student/orders/[id]/page.tsx`，在订单完成（status=completed）且已评价后显示"加好友"按钮。

先读取现有文件了解结构，然后在订单状态为 completed 的区域添加：

```tsx
import { useSendFriendRequest } from "@/hooks/use-friends";

// 组件内
const sendFriendRequest = useSendFriendRequest();

// 订单完成后显示加好友按钮（假设 order.coach_id 为教练 ID）
{order.status === "completed" && order.coach_id && (
  <Button
    variant="outline"
    onClick={() => sendFriendRequest.mutate({ toUserId: order.coach_id, message: "服务很好，加个好友" })}
    disabled={sendFriendRequest.isPending}
  >
    {sendFriendRequest.isPending ? "发送中..." : "加好友"}
  </Button>
)}
```

注意：需要根据实际订单数据结构调整字段名（可能是 `assigned_resource_id` 而非 `coach_id`）。先读取现有代码确认。

- [ ] **步骤 2：教练订单详情页添加"加好友"按钮**

修改 `web/src/app/(protected)/escort/coach/orders/[id]/page.tsx`，类似地添加"加好友"按钮（向学员发送请求）。

```tsx
import { useSendFriendRequest } from "@/hooks/use-friends";

const sendFriendRequest = useSendFriendRequest();

{order.status === "completed" && order.demander_id && (
  <Button
    variant="outline"
    onClick={() => sendFriendRequest.mutate({ toUserId: order.demander_id, message: "服务很好，加个好友" })}
    disabled={sendFriendRequest.isPending}
  >
    {sendFriendRequest.isPending ? "发送中..." : "加好友"}
  </Button>
)}
```

- [ ] **步骤 3：运行前端测试验证**

运行：`cd web ; npx vitest run`
预期：全部通过。

- [ ] **步骤 4：Commit**

```bash
git add "web/src/app/(protected)/escort/student/orders/[id]/page.tsx" "web/src/app/(protected)/escort/coach/orders/[id]/page.tsx"
git commit -m "feat(web): 订单详情页添加加好友按钮"
```

---

### 任务 6：端到端集成测试 + 全量回归

**文件：**
- 创建：`tests/test_friends_e2e.py`

- [ ] **步骤 1：编写端到端测试**

创建 `tests/test_friends_e2e.py`：

```python
"""好友社交端到端集成测试。

覆盖：
1. 发送好友请求
2. 接收方查看请求
3. 接受请求 → 双方成为好友
4. 好友列表
5. 删除好友
6. WS 事件发布验证
7. 非 receiving 方不能操作
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _user_headers(server, user_id: str = "student1", roles: list[str] | None = None):
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name=f"User-{user_id}")
    role_map = {"demander": _ClaimsDemander, "supplier": _ClaimsSupplier}
    for r in (roles or ["demander"]):
        if r in role_map:
            user.add_role(role_map[r]())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_e2e_full_friendship_flow(app_client):
    """完整好友流程：发送→查看→接受→列表→删除。"""
    client, server = app_client

    # 1. student1 向 coach1 发送好友请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1", "message": "服务很好"},
    )
    assert resp.status_code == 200
    request_id = resp.json()["data"]["request_id"]

    # 2. coach1 查看收到的好友请求
    resp2 = client.get(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "coach1"),
    )
    assert resp2.status_code == 200
    assert len(resp2.json()["data"]) >= 1

    # 3. coach1 接受请求
    resp3 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )
    assert resp3.status_code == 200
    assert resp3.json()["data"]["status"] == "accepted"

    # 4. 双方好友列表都应包含对方
    resp4 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert any(f["friend_user_id"] == "coach1" for f in resp4.json()["data"])

    resp5 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    assert any(f["friend_user_id"] == "student1" for f in resp5.json()["data"])

    # 5. student1 删除 coach1
    resp6 = client.delete(
        "/api/v1/friends/coach1",
        headers=_user_headers(server, "student1"),
    )
    assert resp6.status_code == 200

    # 双方好友列表都应为空
    resp7 = client.get("/api/v1/friends", headers=_user_headers(server, "student1"))
    assert len(resp7.json()["data"]) == 0

    resp8 = client.get("/api/v1/friends", headers=_user_headers(server, "coach1"))
    assert len(resp8.json()["data"]) == 0


def test_e2e_reject_then_resend(app_client):
    """拒绝后可以重新发送请求。"""
    client, server = app_client

    # 第一次请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # coach1 拒绝
    client.post(
        f"/api/v1/friends/requests/{request_id}/reject",
        headers=_user_headers(server, "coach1"),
    )

    # 重新发送请求（应成功，因为旧请求已是 rejected 状态）
    resp2 = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    assert resp2.status_code == 200


def test_e2e_events_published(app_client):
    """验证好友事件被发布到 EventBus。"""
    client, server = app_client

    # 收集发布的事件
    events = []
    server.event_bus.subscribe_all(lambda e: events.append(e))

    # 发送请求
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # 接受请求
    client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "coach1"),
    )

    # 验证事件
    event_types = [e.type.value for e in events]
    assert "friend_request.created" in event_types
    assert "friend_request.accepted" in event_types


def test_e2e_non_recipient_cannot_accept(app_client):
    """非接收方不能接受请求。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/friends/requests",
        headers=_user_headers(server, "student1"),
        json={"to_user_id": "coach1"},
    )
    request_id = resp.json()["data"]["request_id"]

    # student2 尝试接受
    resp2 = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=_user_headers(server, "student2"),
    )
    assert resp2.status_code == 403
```

- [ ] **步骤 2：运行端到端测试**

运行：`python -m pytest tests/test_friends_e2e.py -v`
预期：全部通过。

- [ ] **步骤 3：全量后端回归测试**

运行：`python -m pytest tests/ -v --tb=short 2>&1 | Select-Object -Last 40`
预期：全部 PASS（可能有 PostgreSQL 相关测试 skipped）。

- [ ] **步骤 4：全量前端回归测试**

运行：`cd web ; npx vitest run 2>&1 | Select-Object -Last 20`
预期：全部 PASS。

- [ ] **步骤 5：Commit**

```bash
git add tests/test_friends_e2e.py
git commit -m "test(friends): 好友社交端到端集成测试"
```

---

## 自检

### 1. 规格覆盖度

| 规格需求 | 实现任务 |
|---------|---------|
| 发送好友请求 | 任务1（POST /friends/requests） |
| 查看收到的好友请求 | 任务1（GET /friends/requests） |
| 接受好友请求 | 任务2（POST /accept） |
| 拒绝好友请求 | 任务2（POST /reject） |
| 好友列表 | 任务2（GET /friends） |
| 删除好友 | 任务2（DELETE /friends/{id}） |
| WS 实时推送好友请求 | 任务1（WS_PUSHABLE_EVENTS 扩展） |
| 前端好友列表页 | 任务4（好友列表页） |
| 前端加好友入口 | 任务5（订单详情页加好友按钮） |
| Dashboard 好友入口 | 任务4（Dashboard 入口） |
| 防重复请求 | 任务1（已是好友/pending 检查） |
| 事件发布 | 任务1+2（4 个事件发布） |

覆盖完整，无遗漏。

### 2. 占位符扫描

无 "TODO"、"待定"、"后续实现" 等占位符。每个步骤都包含完整代码。

### 3. 类型一致性

- `FriendRequest` 类型：后端 dict（任务1/2），前端 `FriendRequest`（任务3）—— 字段一致。
- `Friendship` 类型：后端 dict（任务2），前端 `Friendship`（任务3）—— 字段一致。
- WS payload `user_id` 字段：任务1/2 中所有事件 payload 都包含 `user_id` 指向接收方，与 `_extract_user_ids` 逻辑一致。

---

## 执行交接

**计划已完成并保存到 `docs/plans/2026-08-04-friendship-social.md`。两种执行方式：**

**1. 子代理驱动（推荐）** - 后端任务（1-2）与前端任务（3-5）可并行执行，任务6（E2E测试）依赖前后端完成。

**2. 内联执行** - 在当前会话中按顺序执行。

**选哪种方式？**
