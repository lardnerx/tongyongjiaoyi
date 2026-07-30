# HTTP API + JWT 认证（阶段五B）说明文档

**阶段**：五 B（HTTP API + JWT 认证）
**适用范围**：`umcp_core.transport` 子包——将 `UMCPServer` 暴露为 FastAPI 应用，提供 RESTful API + WebSocket 推送，使用 JWT 做会话认证
**文档定位**：面向核心库使用者和运维开发者，完整说明传输层的架构、JWT 认证机制、统一响应信封、异常处理、WebSocket 推送、Prometheus 指标、各 router 端点清单、使用方法、测试覆盖与已知限制。

---

## 一、概述

### 1.1 阶段目标

阶段五 B 的目标是为 `UMCPServer` 暴露一层**薄壳**式的 HTTP/WS 传输层：RESTful API 供外部客户端调用，WebSocket 供实时事件推送，JWT 做无状态会话认证。HTTP 层只做协议翻译与身份校验，业务逻辑全部委托给既有的 `UMCPServer`（含 L1-L7 协议栈、6 个仓储、EventBus）。

技术栈：FastAPI 0.110+ / Pydantic v2 / PyJWT 2.8+ / Uvicorn / prometheus_client。

### 1.2 解决的问题

在阶段五 B 之前，`UMCPServer` 只能通过 Python SDK 编程式调用，存在三个缺口：

- **无 HTTP 接入**：外部系统（浏览器、移动端、第三方服务）无法调用核心库能力，每次集成都要写 Python 胶水代码。
- **无身份认证**：`AuthProvider`（L1）只解决"凭据验证"，不解决"会话保持"。每次调用都要重新验证凭据，无法支撑有状态交互。
- **无实时推送**：`EventBus` 是进程内同步分发，外部客户端无法感知任务/交易状态变化，只能轮询。

### 1.3 核心设计

阶段五 B 引入 `transport/` 子包作为 HTTP/WS 绑定层，核心决策如下：

| 决策项 | 选择 | 理由 |
|--------|------|------|
| Web 框架 | FastAPI | 原生 async、自动 OpenAPI、内置 WebSocket、Pydantic 类型校验 |
| 认证模式 | JWT 叠加在 AuthProvider 之上 | 登录时调用 AuthProvider 验证身份并签发 JWT；后续请求仅校验 JWT，不查库。L1 接口零修改 |
| Token 策略 | access (1h) + refresh (7d) + 轮换 | access 短命降泄露风险，refresh 续期 access；refresh 轮换防重放 |
| 黑名单 | 内存 `set[jti]` | YAGNI，单进程足够，生产可换 Redis（阶段五C） |
| WS 推送模型 | 用户维度流 | 按 `user_id` 过滤推送，隐私安全，多端同步 |
| 返回格式 | 统一信封 + 错误码分段 | `{"code": 0, "data": ..., "message": "ok"}`，错误码 1xxx/2xxx/3xxx/5xxx |
| 指标 | Prometheus | `http_requests_total` + `http_request_duration_seconds`，`/metrics` 端点供 scrape |

整体架构：

```
┌─────────────────────────────────────────────────────┐
│              Client (Browser / SDK)                  │
└─────────────────────────────────────────────────────┘
       │ HTTP REST                │ WebSocket
       ↓                          ↓
┌─────────────────────────────────────────────────────┐
│              transport/ 子包（HTTP/WS 绑定层）        │
│  ┌─────────────────────────────────────────────┐    │
│  │ FastAPI app（create_app 工厂）                │    │
│  │  ├─ routers/ (8 个资源域 router)              │    │
│  │  ├─ auth.py (JwtService + 登录/刷新/登出)     │    │
│  │  ├─ deps.py (get_current_user Bearer 依赖)    │    │
│  │  ├─ ws.py (ConnectionManager + EventBus 桥接) │    │
│  │  ├─ errors.py (统一异常处理器)                 │    │
│  │  ├─ schemas.py (Pydantic 请求/响应模型)        │    │
│  │  ├─ metrics.py (Prometheus 中间件 + /metrics)  │    │
│  │  └─ /metrics, /api/v1/ws/events 端点          │    │
│  └─────────────────────────────────────────────┘    │
│         ↓ 委托                                       │
│  ┌─────────────────────────────────────────────┐    │
│  │ UMCPServer (现有，新增 publish_and_match)     │    │
│  │  ├─ 7 层协议栈 (L1-L7)                       │    │
│  │  ├─ 6 个 Repository (内存/PG)                │    │
│  │  ├─ EventBus (事件分发)                      │    │
│  │  └─ execute_composite / publish_and_match    │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

---

## 二、目录结构

`transport/` 子包的文件树与职责：

```
src/umcp_core/transport/
├── __init__.py                # 导出 create_app
├── __main__.py                # 应用入口（python -m umcp_core.transport）
├── app.py                     # create_app 应用工厂 + lifespan + WS 端点
├── config.py                  # TransportConfig + from_env
├── deps.py                    # 依赖注入：get_current_user / get_server / get_jwt_service
├── auth.py                    # JwtService（签发/校验/吊销）+ user_from_claims
├── errors.py                  # ApiError 异常体系 + register_exception_handlers
├── schemas.py                 # Pydantic 统一信封（Envelope / ok / paginated）
├── ws.py                      # ConnectionManager + EventBus→WS 桥接
├── metrics.py                 # Prometheus 指标 + MetricsMiddleware
└── routers/
    ├── __init__.py            # register_routers(app) 聚合
    ├── auth.py                # /api/v1/auth/*  登录/刷新/登出/当前用户
    ├── tasks.py               # /api/v1/tasks/* 任务 CRUD + 取消/完成
    ├── resources.py           # /api/v1/resources/* 资源注册/查询/状态
    ├── matches.py             # /api/v1/matches/* 手动触发匹配
    ├── deals.py                # /api/v1/deals/* 交易创建/激活/完成/争议/取消/解决
    ├── trust.py               # /api/v1/trust/* 信任画像/聚合分/评价
    ├── events.py              # /api/v1/events/* 事件日志查询
    └── health.py              # /api/v1/health, /api/v1/health/ready
```

### 文件职责说明

| 文件 | 职责 |
|------|------|
| `transport/__init__.py:6` | 导出 `create_app`，供 `from umcp_core.transport import create_app` 使用 |
| `transport/app.py:37` | `create_app(server, config)` 应用工厂：构造 JwtService、ConnectionManager，注册 lifespan/CORS/中间件/异常处理器/路由/`/metrics`/WS 端点 |
| `transport/config.py:18` | `TransportConfig` 数据类 + `from_env()` 环境变量加载（含 JWT、CORS、DB 连接池参数） |
| `transport/deps.py:27` | `get_current_user` 依赖：解码 JWT → 检查黑名单 → 重建 User |
| `transport/auth.py:16` | `JwtService` 签发/校验/吊销；`user_from_claims` 从 claims 重建轻量 User |
| `transport/errors.py:15` | `ApiError` 基类 + 8 个子类（映射错误码与 HTTP 状态）；`register_exception_handlers` 注册三类全局处理器 |
| `transport/schemas.py:12` | `Envelope` 统一信封、`PaginatedData` 分页模型、`ok()` / `paginated()` 构造函数 |
| `transport/ws.py:42` | `ConnectionManager` 按 user_id 维护连接；`make_ws_event_bridge` 把 EventBus 同步事件投递到异步事件循环 |
| `transport/metrics.py:28` | `MetricsMiddleware` 记录每请求计数与耗时；`metrics_response()` 返回 Prometheus 文本 |
| `transport/routers/__init__.py:13` | `register_routers(app)` 聚合 8 个 router 到 `/api/v1` 前缀 |
| `transport/__main__.py:22` | `main()` 入口：加载配置 → 构造 server → `create_app` → `uvicorn.run` |

---

## 三、核心设计

### 3.1 应用工厂与 lifespan

`create_app(server, config)` 位于 `src/umcp_core/transport/app.py:37`，是整个传输层的入口。它接收一个**已配置好的** `UMCPServer`（含仓储、插件、策略）和 `TransportConfig`，返回 FastAPI 应用实例。

应用工厂的组装顺序（`app.py:47-102`）：

1. `_setup_logging()` 加载 `logging.conf`（`app.py:47`）
2. 构造 `JwtService` 单例（`app.py:48-52`）
3. 构造 `ConnectionManager` 单例（`app.py:53`）
4. 定义 `lifespan` 异步上下文管理器（`app.py:56-72`）
5. 创建 `FastAPI` 实例并注入 `app.state`（`app.py:74-84`）
6. 添加 CORS 中间件（`app.py:87-93`）
7. 添加 Prometheus `MetricsMiddleware`（`app.py:96`）
8. 注册异常处理器（`app.py:99`）
9. 注册路由（`app.py:102`）
10. 注册 `/metrics` 端点（`app.py:105-108`）
11. 注册 WebSocket 端点（`app.py:111-145`）

`lifespan` 负责启动/关闭钩子（`app.py:56-72`）：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    loop = asyncio.get_event_loop()
    bridge = make_ws_event_bridge(ws_manager, loop)
    server.event_bus.subscribe_all(bridge)
    yield
    # shutdown
    server.event_bus.unsubscribe_all(ws_bridge_ref["bridge"])
    await ws_manager.disconnect_all()
    server.stop()
    server.dispose()
```

- **启动时**：捕获主事件循环，构造 WS 桥接函数并订阅到 `EventBus`。
- **关闭时**：取消订阅、断开所有 WS 连接、调用 `server.stop()` 与 `server.dispose()` 释放底层资源（`app.py:70-71`）。

### 3.2 JWT 认证机制

#### 3.2.1 JwtService

`JwtService` 位于 `src/umcp_core/transport/auth.py:16`，负责 token 的签发、校验与吊销。

| 方法 | 位置 | 说明 |
|------|------|------|
| `__init__(secret, access_ttl=3600, refresh_ttl=604800)` | `auth.py:23` | 持有密钥、TTL、内存黑名单 `set[str]` 与 `RLock` |
| `issue(user)` | `auth.py:35` | 签发 access + refresh token 对 |
| `decode(token)` | `auth.py:72` | 解码并验签，失败抛 `pyjwt.InvalidTokenError` 子类 |
| `revoke(jti)` | `auth.py:76` | 将 jti 加入黑名单 |
| `is_revoked(jti)` | `auth.py:81` | 检查 jti 是否在黑名单 |

#### 3.2.2 access token 与 refresh token

`issue()` 方法（`auth.py:35-70`）签发一对 token，关键设计是 **access token 嵌入 `refresh_jti` 字段**（`auth.py:54`），便于 logout 时一并吊销关联的 refresh token：

```python
refresh_jti = uuid.uuid4().hex
access_payload = {
    **base_claims,
    "iat": now,
    "exp": now + timedelta(seconds=self._access_ttl),
    "jti": uuid.uuid4().hex,
    "type": "access",
    "refresh_jti": refresh_jti,   # 关联 refresh token 的 jti
}
refresh_payload = {
    **base_claims,
    "iat": now,
    "exp": now + timedelta(seconds=self._refresh_ttl),
    "jti": refresh_jti,            # 与 access.refresh_jti 一致
    "type": "refresh",
}
```

JWT Claims 结构：

```json
{
  "sub": "u_abc123",
  "name": "13800000000",
  "roles": ["demander", "supplier"],
  "active_role": "demander",
  "iat": 1719600000,
  "exp": 1719603600,
  "jti": "uuid",
  "type": "access",
  "refresh_jti": "uuid"
}
```

#### 3.2.3 登录流程

`POST /api/v1/auth/login`（`routers/auth.py:45`）：

```
1. 客户端 POST {credential_type, token}
2. AuthRouter 调用 server.auth_provider.authenticate(Credential)
   → 返回 User 对象（AuthProvider 不变，L1 零修改）
3. JwtService.issue(user) 签发 access + refresh
4. 返回 {access_token, refresh_token, token_type, expires_in}
```

#### 3.2.4 请求认证流程

`get_current_user` 依赖（`deps.py:27-42`）：

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> User:
    try:
        payload = jwt_service.decode(token)
    except pyjwt.ExpiredSignatureError as e:
        raise TokenExpiredError() from e
    except pyjwt.InvalidTokenError as e:
        raise InvalidCredentialError(message=f"无效 token: {e}") from e
    if jwt_service.is_revoked(payload.get("jti", "")):
        raise InvalidCredentialError(message="token 已吊销")
    return user_from_claims(payload)
```

- 解码失败（过期）→ `TokenExpiredError`（1002, 401）
- 解码失败（其他）→ `InvalidCredentialError`（1001, 401）
- jti 在黑名单 → `InvalidCredentialError`（1001, 401）
- 成功 → 从 claims 重建 User，**不查库**

#### 3.2.5 刷新与吊销

- **`POST /auth/refresh`**（`routers/auth.py:61`）：用 refresh_token 换新 access_token。实现**token 轮换**——吊销旧 refresh_token 的 jti（`routers/auth.py:76-79`），防止重放。
- **`POST /auth/logout`**（`routers/auth.py:87`）：从 `Authorization` header 提取 token 解码，同时吊销 access token 的 `jti` 与 access 中嵌入的 `refresh_jti`（`routers/auth.py:96-111`）。

#### 3.2.6 User 重建

`user_from_claims(payload)` 位于 `auth.py:87`，从 JWT claims 重建轻量 User 对象：

- 构造 `_ClaimsUser`（`auth.py:126`），其 `authenticate` 永远返回 True（已通过 JWT 校验）
- 按 claims 中的 `roles` 列表添加 `_ClaimsDemander` / `_ClaimsSupplier`（`auth.py:108-123`）
- 切换到 `active_role`
- 未知 role_type 被忽略（容错）

### 3.3 统一响应信封

`Envelope` 定义于 `src/umcp_core/transport/schemas.py:12`：

```python
class Envelope(BaseModel, Generic[T]):
    code: int = 0
    data: T | None = None
    message: str = "ok"
```

成功响应：`{"code": 0, "data": ..., "message": "ok"}`
错误响应：`{"code": <int>, "message": "...", "details": ...}`

构造函数：

| 函数 | 位置 | 用途 |
|------|------|------|
| `ok(data=None, message="ok")` | `schemas.py:44` | 构造成功响应 |
| `paginated(items, total, page, size)` | `schemas.py:49` | 构造分页响应，data 为 `PaginatedData` |

`PaginatedData`（`schemas.py:28`）：`{items, total, page, size}`，分页查询统一返回此结构。

### 3.4 异常处理体系

#### 3.4.1 ApiError 异常体系

`ApiError` 基类位于 `src/umcp_core/transport/errors.py:15`，携带 `code` / `message` / `status` / `details` 四个字段。8 个子类按错误码分段映射 HTTP 状态码：

| 子类 | 错误码 | HTTP 状态 | 位置 |
|------|--------|-----------|------|
| `InvalidCredentialError` | 1001 | 401 | `errors.py:33` |
| `TokenExpiredError` | 1002 | 401 | `errors.py:38` |
| `PermissionDeniedError` | 1003 | 403 | `errors.py:43` |
| `NotFoundError` | 2001 | 404 | `errors.py:49` |
| `IllegalStateError` | 2002 | 409 | `errors.py:54` |
| `ValidationError` | 2003 | 422 | `errors.py:59` |
| `MatchFailedError` | 3001 | 422 | `errors.py:65` |
| `PaymentFailedError` | 3002 | 422 | `errors.py:70` |

错误码分段约定：

| 段 | 含义 |
|----|------|
| 0 | 成功 |
| 1xxx | 认证类 |
| 2xxx | 资源类 |
| 3xxx | 业务类 |
| 5xxx | 系统类（5000 服务器内部错误） |

#### 3.4.2 异常处理器注册

`register_exception_handlers(app)` 位于 `errors.py:75`，注册三类全局处理器：

| 处理器 | 捕获异常 | 响应 |
|--------|---------|------|
| `_handle_api_error` | `ApiError` 及子类 | `{code, message, details}` + `exc.status` |
| `_handle_validation` | `RequestValidationError` | `{code: 2003, message: "参数校验失败", details: errors()}` + 422 |
| `_handle_unknown` | `Exception`（兜底） | `{code: 5000, message: "服务器内部错误"}` + 500，并记录异常日志 |

#### 3.4.3 领域异常翻译

router 层负责把领域异常（`RuntimeError` / `ValueError`）包成 `ApiError`。例如 `task.cancel()` 抛 `RuntimeError("状态机非法转移")` → router catch 后抛 `IllegalStateError(2002, ..., 409)`。集中在 router 而非全局，因为不同领域操作对同一异常可能有不同 HTTP 语义。

### 3.5 依赖注入

`deps.py` 提供三个依赖函数，构成 FastAPI 的 Depends 链路：

| 依赖 | 位置 | 返回 | 来源 |
|------|------|------|------|
| `get_server(request)` | `deps.py:17` | `UMCPServer` | `app.state.server` |
| `get_jwt_service(request)` | `deps.py:22` | `JwtService` | `app.state.jwt_service` |
| `get_current_user(token, jwt_service)` | `deps.py:27` | `User` | 解码 JWT + 重建 |

`oauth2_scheme`（`deps.py:14`）配置为 `OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")`，从 `Authorization: Bearer <token>` 提取 token。

调用链：

```
路由处理函数
  └─ Depends(get_current_user)
       ├─ Depends(oauth2_scheme)          → 提取 token（缺失抛 401）
       └─ Depends(get_jwt_service)        → JwtService 单例
            └─ Depends(get_server)        → UMCPServer 单例（部分路由也直接依赖）
```

### 3.6 WebSocket 事件推送

#### 3.6.1 端点

WS 端点定义于 `app.py:111-145`，路径 `WS /api/v1/ws/events`：

- 客户端通过 query 参数 `?token=<access_token>` 认证（兼容浏览器原生 WebSocket）
- 服务端校验 JWT（`app.py:124`）→ 检查黑名单（`app.py:128`）→ 重建 User（`app.py:133`）
- 校验通过后注册到 `ConnectionManager`（`app.py:134`）
- 循环接收客户端消息，`ping` 回 `pong`（`app.py:140-141`）
- 断开时清理连接（`app.py:145`）

#### 3.6.2 ConnectionManager

`ConnectionManager` 位于 `ws.py:42`，按 `user_id` 维护活跃连接（多端同步）：

| 方法 | 位置 | 说明 |
|------|------|------|
| `connect(ws, user)` | `ws.py:49` | `ws.accept()` + 注册到 `user_id → set[WebSocket]` |
| `disconnect(ws, user)` | `ws.py:55` | 移除连接，空 set 时删 key |
| `send_to_user(user_id, message)` | `ws.py:64` | 推送给该用户所有连接，失败连接被清理 |
| `disconnect_all()` | `ws.py:84` | 关闭所有连接（应用停止时调用） |

并发安全：所有 `_connections` 访问通过 `threading.RLock` 保护（`ws.py:47`）。

#### 3.6.3 EventBus → WebSocket 桥接

`make_ws_event_bridge(manager, loop)` 位于 `ws.py:122`，构造一个同步回调函数注册到 `EventBus.subscribe_all`。EventBus 是同步调用，WebSocket 是异步推送，用 `asyncio.run_coroutine_threadsafe` 把推送投递到主事件循环（`ws.py:140-144`）：

```python
def _bridge(event: Event) -> None:
    if event.type not in WS_PUSHABLE_EVENTS:
        return
    user_ids = _extract_user_ids(event)
    if not user_ids:
        return
    message = _format_ws_message(event)
    for uid in user_ids:
        fut = asyncio.run_coroutine_threadsafe(
            manager.send_to_user(uid, message),
            loop,
        )
        fut.add_done_callback(_log_future_exception)
```

- `_extract_user_ids(event)`（`ws.py:97`）：从 payload 提取 `demander_id` / `supplier_id` / `user_id` 字段
- `_format_ws_message(event)`（`ws.py:112`）：构造 `{type, timestamp, data}` 推送消息
- `_log_future_exception(fut)`（`ws.py:149`）：记录协程异常，避免静默吞掉

#### 3.6.4 WS_PUSHABLE_EVENTS 白名单

`WS_PUSHABLE_EVENTS` 定义于 `ws.py:21`，只推送业务事件，不推内部桥接事件：

```python
WS_PUSHABLE_EVENTS: set[EventType] = {
    EventType.TASK_PUBLISHED, EventType.TASK_ASSIGNED,
    EventType.TASK_COMPLETED, EventType.TASK_CANCELLED,
    EventType.RESOURCE_REGISTERED, EventType.RESOURCE_STATUS_CHANGED,
    EventType.DEAL_CREATED, EventType.DEAL_PAID,
    EventType.DEAL_COMPLETED, EventType.DEAL_DISPUTED,
    EventType.DEAL_CANCELLED, EventType.DEAL_RESOLVED,
    EventType.SUBTASK_COMPLETED, EventType.SUBTASK_CANCELLED,
    EventType.TRUST_UPDATED, EventType.ANOMALY_DETECTED,
    EventType.DISPUTE_OPENED,
}
```

推送消息格式：

```json
{
  "type": "task.completed",
  "timestamp": "2026-07-29T10:00:00+00:00",
  "data": {"task_id": "t_abc", "status": "completed"}
}
```

### 3.7 Prometheus 指标集成

`metrics.py` 定义两个核心指标和一个中间件：

| 指标 | 类型 | 标签 | 位置 |
|------|------|------|------|
| `http_requests_total` | Counter | method, path, status | `metrics.py:14` |
| `http_request_duration_seconds` | Histogram | method, path | `metrics.py:20` |

`MetricsMiddleware`（`metrics.py:28`）继承 `BaseHTTPMiddleware`，记录每个 HTTP 请求的计数与耗时：

- `/metrics` 自身不记录，避免自激（`metrics.py:37`）
- 用路由路径模板（如 `/api/v1/deals/{deal_id}`）而非真实 URL 作为 `path` 标签，避免高基数（`metrics.py:45-46`）

`/metrics` 端点注册在 `app.py:105-108`，不走 `/api/v1` 前缀，便于 scrape 配置。返回 `generate_latest()` 的 Prometheus 文本格式（`metrics.py:61`）。

中间件在 `create_app` 中通过 `app.add_middleware(MetricsMiddleware)` 注册（`app.py:96`）。

### 3.8 各 router 端点清单

所有端点前缀 `/api/v1`。统一信封：成功 `{"code": 0, "data": ..., "message": "ok"}`。

#### 3.8.1 认证（`/auth`）

| 方法 | 路径 | 鉴权 | 说明 | 位置 |
|------|------|------|------|------|
| POST | `/auth/login` | 否 | 凭据登录，返回 access + refresh token | `routers/auth.py:45` |
| POST | `/auth/refresh` | refresh token | 刷新 access token，吊销旧 refresh（轮换） | `routers/auth.py:61` |
| POST | `/auth/logout` | 是 | 吊销当前 access + 关联 refresh token | `routers/auth.py:87` |
| GET | `/auth/me` | 是 | 返回当前用户信息 | `routers/auth.py:115` |

#### 3.8.2 任务（`/tasks`）

| 方法 | 路径 | 鉴权 | 说明 | 位置 |
|------|------|------|------|------|
| POST | `/tasks` | 是 | 发布标准任务并匹配（调用 `server.publish_and_match`） | `routers/tasks.py:51` |
| GET | `/tasks` | 是 | 查询任务列表（`?status=&domain_tag=&page=&size=`） | `routers/tasks.py:76` |
| GET | `/tasks/{task_id}` | 是 | 查询单任务详情 | `routers/tasks.py:104` |
| POST | `/tasks/{task_id}/cancel` | 是 | 取消任务 | `routers/tasks.py:117` |
| POST | `/tasks/{task_id}/complete` | 是 | 标记任务完成 | `routers/tasks.py:138` |

#### 3.8.3 资源（`/resources`）

| 方法 | 路径 | 鉴权 | 说明 | 位置 |
|------|------|------|------|------|
| POST | `/resources` | 是 | 注册资源（supplier 角色） | `routers/resources.py:69` |
| GET | `/resources` | 是 | 查询资源（`?domain_tag=&status=&supplier_id=`） | `routers/resources.py:95` |
| GET | `/resources/{resource_id}` | 是 | 查询单资源详情 | `routers/resources.py:126` |
| POST | `/resources/{resource_id}/status` | 是 | 更新资源状态 | `routers/resources.py:139` |

#### 3.8.4 匹配（`/matches`）

| 方法 | 路径 | 鉴权 | 说明 | 位置 |
|------|------|------|------|------|
| POST | `/matches` | 是 | 手动触发匹配（`{task_id, domain_tag}`） | `routers/matches.py:30` |

#### 3.8.5 交易（`/deals`）

| 方法 | 路径 | 鉴权 | 说明 | 位置 |
|------|------|------|------|------|
| POST | `/deals` | 是 | 创建交易（发布 DEAL_CREATED 事件） | `routers/deals.py:57` |
| GET | `/deals` | 是 | 查询交易（`?task_id=&supplier_id=&status=`） | `routers/deals.py:90` |
| GET | `/deals/{deal_id}` | 是 | 查询交易详情 | `routers/deals.py:121` |
| POST | `/deals/{deal_id}/activate` | 是 | 激活交易 | `routers/deals.py:134` |
| POST | `/deals/{deal_id}/complete` | 是 | 完成交易 | `routers/deals.py:153` |
| POST | `/deals/{deal_id}/dispute` | 是 | 发起争议 | `routers/deals.py:172` |
| POST | `/deals/{deal_id}/cancel` | 是 | 取消交易 | `routers/deals.py:191` |
| POST | `/deals/{deal_id}/resolve` | 是 | 解决争议 | `routers/deals.py:210` |

#### 3.8.6 信任（`/trust`）

| 方法 | 路径 | 鉴权 | 说明 | 位置 |
|------|------|------|------|------|
| GET | `/trust/profiles/{user_id}` | 是 | 查询用户信任画像（`?domain_tag=`） | `routers/trust.py:43` |
| GET | `/trust/profiles/{user_id}/aggregate` | 是 | 查询跨 domain 聚合信任分 | `routers/trust.py:66` |
| POST | `/trust/evaluations` | 是 | 提交评价 | `routers/trust.py:79` |

#### 3.8.7 事件（`/events`）

| 方法 | 路径 | 鉴权 | 说明 | 位置 |
|------|------|------|------|------|
| GET | `/events` | 是 | 查询事件日志（`?event_type=&page=&size=`） | `routers/events.py:37` |
| GET | `/events/{event_id}` | 是 | 查询单事件详情 | `routers/events.py:65` |

#### 3.8.8 健康检查（`/health`，无认证）

| 方法 | 路径 | 说明 | 位置 |
|------|------|------|------|
| GET | `/health` | 存活检查（`{"status": "ok"}`） | `routers/health.py:14` |
| GET | `/health/ready` | 就绪检查（server + 仓储 + DB 连通性） | `routers/health.py:20` |

`/health/ready` 检查 `server.is_running`、`task_repo` 是否注入、DB 连通性（若启用 PG 则 `task_repo.list_all()` 探活，否则标记 `in-memory`，见 `routers/health.py:28-35`）。

---

## 四、关键实现细节（含已修复的坑）

### 4.1 router 异常捕获需同时捕获 RuntimeError 和 ValueError

**问题**：FSM 的 `validate_transition` 抛 `ValueError`（而非 `RuntimeError`），而 router 初版只 `except RuntimeError`，导致非法状态转移返回 500 而非 409。

**修复**：所有涉及状态机操作的 router 改为 `except (RuntimeError, ValueError)`。涉及位置：

| router | 端点 | 位置 |
|--------|------|------|
| tasks | `create_task` | `routers/tasks.py:71` |
| tasks | `cancel_task` | `routers/tasks.py:132` |
| tasks | `complete_task` | `routers/tasks.py:153` |
| deals | `activate_deal` | `routers/deals.py:147` |
| deals | `complete_deal` | `routers/deals.py:166` |
| deals | `dispute_deal` | `routers/deals.py:185` |
| deals | `cancel_deal` | `routers/deals.py:204` |
| deals | `resolve_deal` | `routers/deals.py:224` |

`resources` 的 `update_resource_status` 捕获 `ValueError` 转 `ValidationError`（`routers/resources.py:152`），`register_resource` 捕获 `RuntimeError` 转 `IllegalStateError`（`routers/resources.py:89`）。

### 4.2 `__init__.py` 缺少 create_app 导出

**问题**：实现计划任务 7 创建 `routers/__init__.py` 时引用了尚未创建的 router 模块，导致 `transport/__init__.py` 的 `from umcp_core.transport.app import create_app` 在 app.py 尚未创建时引发循环导入或 `ModuleNotFoundError`。

**修复**：`transport/__init__.py` 显式导出 `create_app`（`transport/__init__.py:6`），且 `app.py` 在函数体内延迟导入 `user_from_claims`（`app.py:132`）避免模块加载期的循环依赖。占位 router 先以空 `APIRouter()` 创建，后续任务逐个替换实现。

### 4.3 logout 实际未吊销 token

**问题**：实现计划初版的 `logout` 只调用 `server.auth_provider.revoke(current_user)`，而 `PhoneAuthProvider.revoke` 是空操作（no-op），token 仍可用，`test_logout_revokes_token` 会失败。

**修复**：改为从 `Authorization` header 提取 token，解码获取 `jti` 与 `refresh_jti`，调用 `jwt_service.revoke` 同时吊销 access token 和关联的 refresh token（`routers/auth.py:96-111`）：

```python
auth_header = request.headers.get("Authorization", "")
token = auth_header.removeprefix("Bearer ").strip()
if token:
    payload = jwt_service.decode(token)
    access_jti = payload.get("jti")
    if access_jti:
        jwt_service.revoke(access_jti)
    refresh_jti = payload.get("refresh_jti")
    if refresh_jti:
        jwt_service.revoke(refresh_jti)
```

配套增强：`JwtService.issue` 在 access token 中嵌入 `refresh_jti` 字段（`auth.py:54`），使 logout 能定位关联的 refresh token。`refresh` 端点也实现 token 轮换——吊销旧 refresh 的 jti（`routers/auth.py:76-79`）。

### 4.4 test_cancel_task 守卫掩盖测试失效

**问题**：实现计划初版的 `test_cancel_task` 用 `if resp.status_code == 200:` 守卫包裹断言。当 `create_task` 因未注册匹配策略返回 500 时，守卫跳过断言，测试"通过"但实际未验证取消逻辑。

**修复**：去掉守卫，直接断言响应状态与错误码。`publish_and_match` 在无匹配策略时抛 `RuntimeError`，router 捕获后返回 `IllegalStateError`（409, 2002）。对于已完成的任务调用 cancel，断言返回 409。

### 4.5 create_task / register_resource 未捕获 RuntimeError 导致 500

**问题**：`create_task` 调用 `server.publish_and_match(task)`，当 domain 未注册匹配策略时抛 `RuntimeError("未注册匹配策略")`；`register_resource` 调用 `res.register()` 时若资源状态非法也抛异常。初版未捕获，导致返回 500。

**修复**：

- `create_task` 用 `try/except (RuntimeError, ValueError)` 包裹 `server.publish_and_match`，转抛 `IllegalStateError`（`routers/tasks.py:69-72`）
- `register_resource` 用 `try/except RuntimeError` 包裹 `res.register()`，转抛 `IllegalStateError`（`routers/resources.py:87-90`）

### 4.6 deals router 显式发布 DEAL_CREATED 事件

`Deal` 领域模型构造时不发事件，`deals` router 在 `create_deal` 中显式调用 `server.event_bus.publish(Event(type=DEAL_CREATED, ...))`（`routers/deals.py:74-86`），使 WS 桥接能推送 `deal.created` 事件。后续 deal 状态变更（activate/complete/dispute/cancel/resolve）通过 `deal.bind_event_bus(server.event_bus)` 绑定总线后再调用状态机方法（`routers/deals.py:144,163,182,201,221`），由领域模型自身发事件。

---

## 五、使用方法

### 5.1 启动服务

**方式一：命令行入口**

```bash
export UMCP_JWT_SECRET=your-secret-key
python -m umcp_core.transport
```

`__main__.py` 的 `main()`（`transport/__main__.py:22`）会读取环境变量、构造 `UMCPServer`（按 `UMCP_DB_DSN` 决定内存或 PG 仓储）、调用 `create_app`、用 uvicorn 启动。

**方式二：uvicorn 直接启动**

```bash
uvicorn umcp_core.transport.app:create_app --factory --host 0.0.0.0 --port 8000
```

**方式三：编程式**

```python
from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
import uvicorn

server = UMCPServer()
server.use_in_memory_repositories()
server.load_plugin("ride_hailing")
server.start()

config = TransportConfig(jwt_secret="your-secret")
app = create_app(server, config)
uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 5.2 环境变量

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `UMCP_JWT_SECRET` | 是 | - | JWT 签名密钥 |
| `UMCP_JWT_ACCESS_TTL` | 否 | 3600 | access token TTL（秒） |
| `UMCP_JWT_REFRESH_TTL` | 否 | 604800 | refresh token TTL（秒） |
| `UMCP_DB_DSN` | 否 | - | PG 连接串（不填则用内存仓储） |
| `UMCP_CORS_ORIGINS` | 否 | `*` | CORS 允许源（逗号分隔） |
| `UMCP_LOG_LEVEL` | 否 | INFO | 日志级别 |
| `UMCP_HOST` | 否 | `0.0.0.0` | 服务监听地址 |
| `UMCP_PORT` | 否 | 8000 | 服务监听端口 |
| `UMCP_DB_POOL_SIZE` | 否 | 10 | DB 连接池大小 |
| `UMCP_DB_MAX_OVERFLOW` | 否 | 20 | 连接池溢出上限 |
| `UMCP_DB_POOL_RECYCLE` | 否 | 3600 | 连接回收周期（秒） |
| `UMCP_DB_POOL_TIMEOUT` | 否 | 30 | 获取连接超时（秒） |

### 5.3 登录获取 token

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"credential_type": "phone", "token": "13800000000"}'
```

响应：

```json
{
  "code": 0,
  "data": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "Bearer",
    "expires_in": 3600
  },
  "message": "ok"
}
```

### 5.4 调用业务 API

```bash
# 发布任务（自动匹配）
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"demander_id": "u1", "domain_tag": "ride", "title": "打车去机场"}'

# 查询任务详情
curl http://localhost:8000/api/v1/tasks/<task_id> \
  -H "Authorization: Bearer <access_token>"

# 创建交易
curl -X POST http://localhost:8000/api/v1/deals \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "resource_id": "res_1", "demander_id": "u1", "supplier_id": "sup1", "final_amount": 88.5}'
```

### 5.5 连接 WebSocket

```bash
# 用 wscat 连接
wscat -c "ws://localhost:8000/api/v1/ws/events?token=<access_token>"
```

连接后可发送 `ping` 收到 `pong`，服务端会在业务事件发生时推送：

```json
{"type": "task.completed", "timestamp": "2026-07-29T10:00:00+00:00", "data": {"task_id": "t_abc"}}
```

### 5.6 Python httpx 示例

```python
import httpx

base = "http://localhost:8000/api/v1"

# 登录
resp = httpx.post(f"{base}/auth/login", json={"credential_type": "phone", "token": "13800000000"})
token = resp.json()["data"]["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 发布任务
resp = httpx.post(f"{base}/tasks", json={"demander_id": "u1", "domain_tag": "ride"}, headers=headers)
task = resp.json()["data"]
assert task["status"] == "completed"

# 创建并完成交易
deal = httpx.post(f"{base}/deals", json={
    "task_id": task["task_id"], "resource_id": "res_1",
    "demander_id": "u1", "supplier_id": "supplier_1", "final_amount": 88.5,
}, headers=headers).json()["data"]
httpx.post(f"{base}/deals/{deal['deal_id']}/activate", headers=headers)
httpx.post(f"{base}/deals/{deal['deal_id']}/complete", headers=headers)

# 查询事件日志
events = httpx.get(f"{base}/events?page=1&size=50", headers=headers).json()["data"]
assert "task.published" in [e["type"] for e in events["items"]]
```

---

## 六、测试覆盖

### 6.1 测试文件清单

| 文件 | 类型 | 覆盖点 |
|------|------|--------|
| `tests/test_jwt_service.py` | 单元 | JwtService 签发/解码/吊销/过期/refresh_jti 嵌入；`user_from_claims` 重建 |
| `tests/test_ws_manager.py` | 单元 | ConnectionManager 连接/断开/多端推送/失败清理；`_extract_user_ids`/`_format_ws_message`；桥接跳过非白名单事件 |
| `tests/test_transport_schemas.py` | 单元 | ApiError 子类错误码与 HTTP 状态映射；`Envelope`/`ok`/`paginated` 构造 |
| `tests/test_transport_config_deps.py` | 集成 | TransportConfig 默认值与 `from_env` 环境变量加载；`get_current_user` 解码有效 token、无 token 返回 401 |
| `tests/test_auth_router.py` | 集成 | 登录返回 token、无效凭据 401、`/me` 鉴权、`/logout` 返回 ok、`/refresh` 返回新 token |
| `tests/test_tasks_resources_matches.py` | 集成 | 任务创建/查询/404/取消；资源注册/查询/状态更新；匹配触发 |
| `tests/test_deals_trust_events.py` | 集成 | 交易创建/查询/激活/完成；信任画像 404/聚合分；事件列表查询 |
| `tests/test_app_factory.py` | 集成 | health 端点、OpenAPI docs、CORS、WS 连接/拒绝无效 token、lifespan 资源释放、日志加载、DB 连接池参数 |
| `tests/test_ws_integration.py` | 集成 | WS 连接后事件推送、无 token 拒绝、无效 token 拒绝、ping/pong |
| `tests/test_http_e2e.py` | E2E | 完整交易闭环（登录→发任务→匹配→创建交易→激活→完成→查询事件）；认证流程；错误处理（404/409） |
| `tests/test_metrics.py` | 单元 | Prometheus 指标记录、`/metrics` 端点 |

### 6.2 关键测试场景

- JWT 过期返回 1002（`test_jwt_service.py` `TestJwtDecode.test_decode_expired_token_raises`）
- 无 token 访问受保护端点返回 401（`test_transport_config_deps.py` `test_get_current_user_missing_token_returns_401`）
- access token 嵌入 `refresh_jti` 与 refresh token 的 jti 一致（`test_jwt_service.py` `test_access_token_contains_refresh_jti`）
- `user_from_claims` 容错：未知 role_type 被忽略、空 claims 不抛异常（`test_jwt_service.py` `TestUserFromClaims`）
- lifespan shutdown 调用 `server.stop()` 与 `server.dispose()`（`test_app_factory.py` `TestLifespanResourceRelease`）
- 完整交易闭环 E2E：登录→发任务→匹配→创建交易→激活→完成→查询事件（`test_http_e2e.py` `TestFullTransactionFlow.test_full_flow`）
- WS 连接后触发任务发布收到 `task.*` 事件推送（`test_ws_integration.py` `TestWsEventPush`）

---

## 七、已知限制

### 7.1 WS 推送链路在阶段五B不完整

阶段五B的 WS 推送存在以下不完整之处，留待阶段五C修复：

- **领域模型发事件覆盖不全**：`Deal` 领域模型构造时不发 `DEAL_CREATED` 事件，由 `deals` router 显式补发（`routers/deals.py:74`）。`Resource` 领域模型同样未发 `RESOURCE_REGISTERED` 等事件，`WS_PUSHABLE_EVENTS` 中预留了这些类型但当前无事件源触发。
- **`_extract_user_ids` 仅从 payload 直读字段**：依赖事件 payload 含 `demander_id` / `supplier_id` / `user_id` 字段。规格设想的 `task_id → demander_id`、`deal_id → [buyer_id, supplier_id]` 缓存映射未实现，部分事件可能因 payload 缺字段而不推送。
- **WS 推送不保证送达**：无 ACK 机制，断连即丢消息。历史事件通过 `GET /events` 查询补全。

### 7.2 `asyncio.get_event_loop()` 弃用警告

`lifespan` 中使用 `asyncio.get_event_loop()`（`app.py:59`）获取主事件循环。在 Python 3.10+ 中此写法在没有运行中事件循环时会触发 `DeprecationWarning`。FastAPI 的 lifespan 上下文保证此时已有运行中的循环，功能正常，但日志可能出现弃用警告。阶段五C应改为 `asyncio.get_running_loop()`。

### 7.3 JWT 短 key 警告

`JwtService` 使用 HS256 对称签名，当 `UMCP_JWT_SECRET` 长度较短（小于 32 字节）时，PyJWT 会发出 `UserWarning` 提示密钥不够安全。生产环境应使用足够长度的随机密钥。

### 7.4 其他限制

- **内存黑名单多进程不一致**：`JwtService._blacklist` 是进程内 `set[jti]`，多进程部署下各 worker 黑名单不同步。单进程足够，多进程需换 Redis（阶段五C）。
- **CORS 默认 `*`**：生产环境应通过 `UMCP_CORS_ORIGINS` 配置具体域名。
- **`_extract_user_ids` 缓存映射不持久化**：server 重启后失效（内存缓存）。
- **角色守卫简化**：当前 router 未严格校验 `demander_id == current_user.user_id`（`routers/tasks.py:59-61` 注释标注），生产环境应补全。
