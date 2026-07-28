# 阶段五 B：HTTP API + JWT 认证 设计规格

> **状态：** 已批准（2026-07-29）
> **目标：** 为 UMCPServer 暴露 RESTful HTTP API + WebSocket，使用 JWT 做会话认证，HTTP 层是薄壳只做协议翻译。
> **前置阶段：** 阶段五 A（PostgreSQL 持久化）已完成，351 passed / 45 skipped。
> **技术栈：** FastAPI + Pydantic v2 + PyJWT + Uvicorn

---

## 1. 架构概述

### 设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| Web 框架 | FastAPI | 原生 async、自动 OpenAPI、内置 WebSocket、Pydantic 类型校验、与 SQLAlchemy 2.0 异步契合 |
| 认证模式 | JWT 叠加在 AuthProvider 之上 | 登录时调用 AuthProvider 验证身份，签发 JWT；后续请求仅校验 JWT，不查库。L1 接口零修改 |
| Token 策略 | access (1h) + refresh (7d) | 平衡安全与体验，refresh 续期 access |
| 黑名单 | 内存 set[jti] + 过期清理 | YAGNI，生产可换 Redis |
| WS 推送模型 | 用户维度流 | 按 user_id 过滤推送，隐私安全，多端同步 |
| API 范围 | 完整 6 资源域 | 一次到位：认证/任务/资源/匹配/交易/信任/事件 |
| 返回格式 | 统一信封 + 错误码分段 | `{"code": 0, "data": ..., "message": "ok"}`，错误码 1xxx/2xxx/3xxx |

### 架构图

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
│  │  ├─ routers/ (7 个资源域 router)              │    │
│  │  ├─ auth.py (JwtService + 登录/刷新/登出)     │    │
│  │  ├─ deps.py (get_current_user Bearer 依赖)    │    │
│  │  ├─ ws.py (ConnectionManager + EventBus 桥接) │    │
│  │  ├─ errors.py (统一异常处理器)                 │    │
│  │  └─ schemas.py (Pydantic 请求/响应模型)        │    │
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

### 新增文件结构

```
src/umcp_core/transport/                # 新增子包
  __init__.py
  app.py                                # create_app(server, config) → FastAPI 应用工厂
  config.py                             # TransportConfig + from_env
  deps.py                               # 依赖注入：get_current_user / get_server / get_jwt_service
  auth.py                               # JwtService 签发/校验/吊销 + 登录端点逻辑
  errors.py                             # ApiError 异常体系 + 异常处理器注册
  schemas.py                            # Pydantic 请求/响应模型（统一信封、分页）
  ws.py                                 # ConnectionManager + EventBus→WS 桥接
  routers/
    __init__.py
    auth.py                             # /auth/*
    tasks.py                            # /tasks/*
    resources.py                        # /resources/*
    matches.py                          # /matches/*
    deals.py                            # /deals/*
    trust.py                            # /trust/*
    events.py                           # /events/*
    health.py                           # /health, /health/ready
tests/
  test_jwt_service.py                   # JwtService 单元测试
  test_ws_manager.py                    # ConnectionManager 单元测试
  test_http_api.py                      # REST 端点集成测试
  test_ws_integration.py                # WebSocket 集成测试
  test_http_e2e.py                      # 完整交易闭环 E2E
```

### 核心库改动

| 改动 | 位置 | 说明 |
|------|------|------|
| 新增方法 | `server.py` | `UMCPServer.publish_and_match(task)`：封装单任务编排（publish → 匹配 → assign → start_execution）。复合任务委托 `execute_composite`。HTTP 层只调用此方法。 |
| 零修改 | `layers/l1/access.py` | `AuthProvider` 接口不变，`PhoneAuthProvider` 等实现不变。JWT 在 transport 层叠加。 |
| 零修改 | `core/`、`events/`、`repositories/` | 领域模型、事件总线、仓储层全部不变。 |

---

## 2. JWT 认证流程

### JWT Claims 结构

```json
{
  "sub": "u_abc123",                   // user_id（必填，来自 User.user_id）
  "name": "13800000000",               // 用户名（来自 User.name）
  "roles": ["demander", "supplier"],   // 角色列表
  "active_role": "demander",           // 当前活动角色
  "iat": 1719600000,                   // 签发时间
  "exp": 1719603600,                   // 过期时间（access 默认 1h）
  "jti": "uuid"                        // JWT ID（用于黑名单吊销）
}
```

### 登录流程

```
1. POST /api/v1/auth/login
   body: {"credential_type": "phone", "token": "13800000000"}
2. AuthRouter 调用 server.auth_provider.authenticate(Credential(type, token))
   → 返回 User 对象
3. JwtService.issue(user) 签发 access_token (1h) + refresh_token (7d)
4. 返回 {"access_token": "...", "refresh_token": "...", "token_type": "Bearer", "expires_in": 3600}
```

### 请求认证流程

```
1. 客户端请求带 Authorization: Bearer <access_token>
2. get_current_user 依赖：
   - 解码 JWT（验签 + 验过期）
   - 检查 jti 是否在黑名单
   - 从 claims 重建 User 对象（不调用 AuthProvider，不查库）
3. 注入 User 到路由处理函数
```

### 刷新与吊销

- `POST /auth/refresh`：用 refresh_token 换新 access_token。refresh_token 也是 JWT，exp 为 7d。
- `POST /auth/logout`：将当前 jti 加入内存黑名单，同步调用 `AuthProvider.revoke(user)`。
- 黑名单用内存 `set[jti]`，启动后台任务定期清理已过期 jti（基于 exp）。

### JwtService 接口

```python
class JwtService:
    def __init__(self, secret: str, access_ttl: int = 3600, refresh_ttl: int = 604800) -> None: ...

    def issue(self, user: User) -> dict[str, Any]:
        """签发 token 对，返回 {"access_token", "refresh_token", "token_type", "expires_in"}。"""

    def decode(self, token: str) -> dict:
        """解码并验证 JWT，失败抛 jwt.InvalidTokenError。"""

    def revoke(self, jti: str) -> None:
        """加入黑名单。"""

    def is_revoked(self, jti: str) -> bool:
        """检查是否在黑名单。"""
```

### 依赖注入

```python
# transport/deps.py
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_jwt_service() -> JwtService: ...           # 单例（app.state）
def get_server() -> UMCPServer: ...                # 应用启动时绑定

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    jwt: JwtService = Depends(get_jwt_service),
) -> User:
    payload = jwt.decode(token)                    # 失败抛 401
    if jwt.is_revoked(payload["jti"]):
        raise InvalidCredentialError(1001, "token 已吊销")
    return _user_from_claims(payload)

async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme, auto_error=False),
    ...
) -> User | None: ...                              # 可选认证
```

### User 重建

从 JWT claims 重建 User，不查库：

```python
def _user_from_claims(payload: dict) -> User:
    """从 JWT claims 重建轻量 User 对象。"""
    # 构造带 roles 和 active_role 的 User 实例
    # 不调用 AuthProvider，每请求零 DB 查询
```

---

## 3. RESTful API 端点

所有端点前缀 `/api/v1`。统一信封：成功 `{"code": 0, "data": ..., "message": "ok"}`，错误 `{"code": <int>, "message": "...", "details": ...}`。

### 3.1 认证（`/auth`）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/auth/login` | 否 | 凭据登录，返回 access+refresh token |
| POST | `/auth/refresh` | refresh token | 刷新 access token |
| POST | `/auth/logout` | 是 | 吊销当前 token |
| GET | `/auth/me` | 是 | 返回当前用户信息 |

### 3.2 任务（`/tasks`）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/tasks` | 是 | 发布标准任务（demander 角色），调用 `server.publish_and_match` |
| POST | `/tasks/composite` | 是 | 发布复合任务（带 subtasks + dependencies），调用 `server.execute_composite` |
| GET | `/tasks` | 是 | 查询任务列表（`?status=&domain_tag=&page=&size=`） |
| GET | `/tasks/{task_id}` | 是 | 查询单任务详情（复合任务返回子任务和依赖） |
| POST | `/tasks/{task_id}/cancel` | 是 | 取消任务 |
| POST | `/tasks/{task_id}/assign` | 是 | 指派资源 |
| POST | `/tasks/{task_id}/complete` | 是 | 标记任务完成 |

### 3.3 资源（`/resources`）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/resources` | 是 | 供应商注册资源 |
| GET | `/resources` | 是 | 查询资源（`?domain_tag=&status=&supplier_id=`） |
| GET | `/resources/{resource_id}` | 是 | 查询单资源详情 |
| POST | `/resources/{resource_id}/status` | 是 | 更新资源状态 |

### 3.4 匹配（`/matches`）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/matches` | 是 | 手动触发匹配（`{"task_id": "...", "domain_tag": "..."}`） |
| GET | `/matches/{task_id}` | 是 | 查询任务的匹配结果 |

### 3.5 交易（`/deals`）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/deals` | 是 | 创建交易 |
| GET | `/deals` | 是 | 查询交易（`?task_id=&supplier_id=&status=`） |
| GET | `/deals/{deal_id}` | 是 | 查询交易详情 |
| POST | `/deals/{deal_id}/pay` | 是 | 发起支付（`{"phase": "deposit\|balance", "amount": ...}`） |
| POST | `/deals/{deal_id}/confirm` | 是 | 确认收款 |
| POST | `/deals/{deal_id}/complete` | 是 | 完成交易 |
| POST | `/deals/{deal_id}/dispute` | 是 | 发起争议 |

### 3.6 信任（`/trust`）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/trust/profiles/{user_id}` | 是 | 查询用户信任画像（`?domain_tag=`） |
| GET | `/trust/profiles/{user_id}/aggregate` | 是 | 查询跨 domain 聚合信任分 |
| POST | `/trust/evaluations` | 是 | 提交评价（4 维度：delivery/quality/service/cost_performance） |
| GET | `/trust/evaluations` | 是 | 查询评价（`?evaluatee_id=&task_id=`） |

### 3.7 事件（`/events`）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/events` | 是 | 查询事件日志（`?event_type=&since=&until=&page=&size=`） |
| GET | `/events/{event_id}` | 是 | 查询单事件详情 |

### 3.8 健康检查（`/health`，无认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 存活检查（`{"status": "ok"}`） |
| GET | `/health/ready` | 就绪检查（检查 server.is_running、仓储连通性） |

### 统一约定

**分页**：`?page=1&size=20`，响应 `{"items": [...], "total": N, "page": 1, "size": 20}`。

**角色守卫**：写操作需对应角色（demander 发任务、supplier 注册资源、双方评价）。路由依赖校验 `current_user.active_role`，未授权返回 403（code=1003）。

**错误码分段**：

| 段 | 含义 | 示例 |
|----|------|------|
| 0 | 成功 | 0 |
| 1xxx | 认证类 | 1001 无效凭据、1002 token 过期、1003 权限不足 |
| 2xxx | 资源类 | 2001 不存在、2002 状态非法、2003 参数校验失败 |
| 3xxx | 业务类 | 3001 匹配失败、3002 支付失败、3003 争议已开启 |
| 5xxx | 系统类 | 5000 服务器内部错误 |

---

## 4. WebSocket 用户维度流

### 端点

```
WS /api/v1/ws/events
  - 客户端连接时携带 Authorization: Bearer <token>
    （或 query 参数 ?token=... 备选，兼容浏览器原生 WebSocket）
  - 服务端校验 JWT，accept 后注册到 ConnectionManager
  - 连接保持期间推送事件
  - 客户端断开时清理
```

### ConnectionManager

```python
class ConnectionManager:
    """按 user_id 维护活跃 WebSocket 连接。"""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}  # user_id → 多连接（多端）
        self._lock: RLock = RLock()                        # 并发安全

    async def connect(self, ws: WebSocket, user: User) -> None: ...
    async def disconnect(self, ws: WebSocket, user: User) -> None: ...
    async def send_to_user(self, user_id: str, message: dict) -> None: ...
    async def disconnect_all(self) -> None: ...            # 应用停止时调用
```

### EventBus → WebSocket 桥接

EventBus 是同步调用，WebSocket 是异步推送。用 `asyncio.run_coroutine_threadsafe` 把推送投递到主事件循环。

```python
def make_ws_event_bridge(manager: ConnectionManager, loop: asyncio.AbstractEventLoop) -> Callable[[Event], None]:
    def _bridge(event: Event) -> None:
        if event.type not in WS_PUSHABLE_EVENTS:
            return
        user_ids = _extract_user_ids(event)
        message = _format_ws_message(event)
        for uid in user_ids:
            asyncio.run_coroutine_threadsafe(
                manager.send_to_user(uid, message),
                loop,
            )
    return _bridge
```

### user_id 提取与缓存

`_extract_user_ids(event)` 根据 payload 的 `task_id`/`deal_id`/`resource_id` 反查关联用户。

为避免每事件查库，缓存映射：
- `task_id → demander_id`
- `deal_id → [buyer_id, supplier_id]`
- `resource_id → supplier_id`

缓存 TTL 5 分钟，或任务/交易终态后清除。

### 推送消息格式

```json
{
  "type": "task.completed",
  "timestamp": "2026-07-29T10:00:00Z",
  "data": {
    "task_id": "t_abc",
    "status": "completed",
    "assigned_resource_id": "r_xyz"
  }
}
```

### 可推送事件白名单

```python
WS_PUSHABLE_EVENTS = {
    EventType.TASK_PUBLISHED, EventType.TASK_ASSIGNED,
    EventType.TASK_COMPLETED, EventType.TASK_CANCELLED,
    EventType.RESOURCE_REGISTERED, EventType.RESOURCE_STATUS_CHANGED,
    EventType.DEAL_CREATED, EventType.DEAL_PAID, EventType.DEAL_COMPLETED,
    EventType.DEAL_DISPUTED,
    EventType.SUBTASK_COMPLETED, EventType.SUBTASK_CANCELLED,
    EventType.TRUST_UPDATED,
    EventType.ANOMALY_DETECTED,
}
```

### 多端同步

同一 user_id 可能有多个连接（手机+网页），`send_to_user` 推送给全部连接。

### 心跳保活

服务端每 30 秒发 `{"type": "ping"}`，客户端 60 秒无响应则断开清理。FastAPI WebSocket 原生不支持 ping/pong 帧，用应用层消息实现。

### 背压保护

若 `send_to_user` 因客户端慢导致积压，单条消息推送超时 5 秒后放弃该连接（标记 dead 清理）。不做消息队列，断连即丢消息。

### 生命周期

`create_app(server)` 时：
1. 创建 `ConnectionManager` 单例
2. 在 `startup` 事件中记录 `asyncio.get_event_loop()`
3. 创建桥接函数并 `server.event_bus.subscribe_all(bridge)` 注册
4. 在 `shutdown` 事件中 `manager.disconnect_all()` 并 `server.event_bus.unsubscribe_all(bridge)`

---

## 5. 错误处理

### 异常体系

```python
# transport/errors.py

class ApiError(Exception):
    """业务错误基类，携带 code 和 HTTP status。"""
    def __init__(self, code: int, message: str, status: int = 400, details: Any = None): ...

class InvalidCredentialError(ApiError):    # 1001, 401
class TokenExpiredError(ApiError):          # 1002, 401
class PermissionDeniedError(ApiError):      # 1003, 403
class NotFoundError(ApiError):              # 2001, 404
class IllegalStateError(ApiError):          # 2002, 409
class ValidationError(ApiError):            # 2003, 422
class MatchFailedError(ApiError):           # 3001, 422
class PaymentFailedError(ApiError):         # 3002, 422
```

### 异常处理器

```python
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request, exc):
        return JSONResponse(exc.status, {"code": exc.code, "message": exc.message, "details": exc.details})

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request, exc):
        return JSONResponse(422, {"code": 2003, "message": "参数校验失败", "details": exc.errors()})

    @app.exception_handler(Exception)
    async def _handle_unknown(request, exc):
        logger.exception("未处理异常")
        return JSONResponse(500, {"code": 5000, "message": "服务器内部错误"})
```

### 领域异常翻译

在 router 层把领域异常包成 ApiError。例如 `task.complete()` 抛 `RuntimeError("状态机非法转移")` → router catch 后抛 `IllegalStateError(2002, "任务状态不允许此操作", 409)`。集中在 router 而非全局，因为不同领域操作对同一异常可能有不同 HTTP 语义。

---

## 6. 测试策略

### 三层测试

| 层 | 文件 | 范围 | 工具 |
|----|------|------|------|
| 单元 | `tests/test_jwt_service.py` | JwtService 签发/解码/吊销/过期 | pytest |
| 单元 | `tests/test_ws_manager.py` | ConnectionManager 连接/断开/多端推送/并发 | pytest + asyncio |
| 集成 | `tests/test_http_api.py` | 全部 REST 端点 + 认证流程 | `fastapi.testclient.TestClient` |
| 集成 | `tests/test_ws_integration.py` | WS 连接 + 事件触发 + 推送验证 | `WebSocketTestSession` |
| E2E | `tests/test_http_e2e.py` | 完整交易闭环 | TestClient + 内存仓储 |

### 关键 fixtures

```python
@pytest.fixture
def jwt_service() -> JwtService:
    return JwtService(secret="test-secret", access_ttl=60)

@pytest.fixture
def http_app(server_with_plugins, jwt_service) -> FastAPI:
    return create_app(server_with_plugins, jwt_secret="test-secret")

@pytest.fixture
def client(http_app) -> TestClient:
    return TestClient(http_app)

@pytest.fixture
def authed_client(client, jwt_service) -> TestClient:
    """预登录的 client，Authorization header 已设置。"""
    user = PhoneAuthProvider().authenticate(Credential("phone", "13800000000"))
    token = jwt_service.issue(user)["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
```

### 关键测试场景

- JWT 过期返回 1002
- 无 token 访问受保护端点返回 401
- 角色不匹配（demander 调 supplier 端点）返回 1003
- 复合任务通过 HTTP 创建并执行，WS 推送 SUBTASK_COMPLETED
- 多端连接同时收到推送
- WS 连接断开后不再收到推送，且不泄漏（manager 清理）

---

## 7. 配置

### 环境变量（12-factor）

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

### TransportConfig

```python
@dataclass
class TransportConfig:
    jwt_secret: str
    jwt_access_ttl: int = 3600
    jwt_refresh_ttl: int = 604800
    db_dsn: str | None = None                 # None 时使用内存仓储
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "TransportConfig": ...
```

### 应用入口

```python
def main() -> None:
    config = TransportConfig.from_env()
    server = UMCPServer()
    if config.db_dsn:
        server.use_postgres_repositories(config.db_dsn)
    else:
        server.use_in_memory_repositories()
    server.load_plugin("plugins/ride_hailing/plugin.json")
    server.start()
    app = create_app(server, config)
    uvicorn.run(app, host=config.host, port=config.port)
```

---

## 8. 新增依赖

```toml
# pyproject.toml [project.optional-dependencies]
http = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.27.0",
    "pyjwt>=2.8.0",
    "pydantic>=2.5.0",
]
dev = [
    # 现有依赖...
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.27.0",
    "pyjwt>=2.8.0",
    "httpx>=0.27.0",              # TestClient 底层依赖
]
```

---

## 9. 不做的事（YAGNI 边界）

- **不做 OAuth2 第三方登录**（微信/Google）：本阶段只暴露 AuthProvider 接口，第三方集成留给插件。
- **不做 API 限流**：留到阶段五C（Docker + 日志 + 监控）一起做。
- **不做请求追踪（OpenTelemetry）**：同上，留到五C。
- **不做 SSE 备选方案**：WebSocket 满足需求，不增加传输方式。
- **不做消息持久化**：WS 推送是"实时通知"，断连即丢；历史事件通过 `GET /events` 查询。

---

## 10. 已知限制

- 内存黑名单在多进程部署下不一致（单进程足够，多进程需换 Redis，留到五C）。
- `_extract_user_ids` 的缓存映射在 server 重启后失效（内存缓存，不持久化）。
- WebSocket 推送不保证送达（无 ACK 机制，断连即丢消息）。
- CORS 默认 `*`，生产环境应配置具体域名。
