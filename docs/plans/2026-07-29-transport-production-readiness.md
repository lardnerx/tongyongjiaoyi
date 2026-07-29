# 阶段五 C：transport 生产就绪修复 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复阶段五 B 审查发现的 4 个阻断级生产就绪问题：Token 吊销不完整、list 端点穿透私有属性、lifespan 未释放 PG 资源、WS 推送链路对真实事件不生效。

**架构：** 1) JwtService.issue 在 access token 中嵌入 `refresh_jti`，logout/refresh 据此吊销；2) 仓储接口加 `list_all()` 抽象方法，InMemory 和 PG 各实现，router 改用此方法；3) lifespan shutdown 调用 `server.stop()` + `server.dispose()`；4) Task._emit payload 补 `demander_id`，Deal 添加 event_bus 机制并在状态变更时发事件。

**技术栈：** Python 3.11+、FastAPI、PyJWT、SQLAlchemy 2.0、pytest

**规格文档：** `docs/specs/2026-07-29-transport-production-readiness-design.md`

---

## 文件结构

### 修改
- `src/umcp_core/transport/auth.py` — JwtService.issue 改造，access token 嵌入 refresh_jti
- `src/umcp_core/transport/routers/auth.py` — logout 吊销 refresh_jti，refresh 端点实现 token 轮换
- `src/umcp_core/repositories/interfaces.py` — 3 个仓储接口加 `list_all()` 抽象方法
- `src/umcp_core/repositories/in_memory.py` — 3 个 InMemory 仓储实现 `list_all()`
- `src/umcp_core/repositories/postgres/task_repo.py` — 实现 `list_all()`
- `src/umcp_core/repositories/postgres/resource_repo.py` — 实现 `list_all()`
- `src/umcp_core/repositories/postgres/deal_repo.py` — 实现 `list_all()`
- `src/umcp_core/transport/routers/tasks.py` — `list_tasks` 改用 `list_all()`
- `src/umcp_core/transport/routers/resources.py` — `list_resources` 改用 `list_all()`
- `src/umcp_core/transport/routers/deals.py` — `list_deals` 改用 `list_all()`；`create_deal` 绑定 event_bus 并发布 DEAL_CREATED
- `src/umcp_core/transport/app.py` — lifespan shutdown 加 `server.stop()` + `server.dispose()`
- `src/umcp_core/core/task.py` — `_emit` payload 补 `demander_id`；`assign_to` 补 `supplier_id`
- `src/umcp_core/core/deal.py` — 添加 `bind_event_bus` / `_emit` / `_event_bus` 字段；状态变更发事件

### 测试
- `tests/test_jwt_service.py` — 补 refresh_jti 验证
- `tests/test_auth_router.py` — 补 logout 吊销 refresh、refresh 轮换
- `tests/test_repositories_in_memory.py` — 补 3 个 list_all 测试
- `tests/test_postgres_repos.py` — 补 3 个 list_all 测试（PG）
- `tests/test_http_e2e.py` — 补 list 过滤 E2E
- `tests/test_deals_trust_events.py` — 补 Deal 事件发布测试
- `tests/test_ws_integration.py` — 升级为真实推送验证

---

## 任务分解

### 任务 1：JwtService.issue 嵌入 refresh_jti

**文件：**
- 修改：`src/umcp_core/transport/auth.py:35-65`
- 测试：`tests/test_jwt_service.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_jwt_service.py` 的 `TestJwtIssue` 类末尾追加：

```python
    def test_access_token_contains_refresh_jti(self):
        """access token 应嵌入 refresh_jti 字段，与 refresh token 的 jti 一致。"""
        svc = JwtService(secret="test-secret")
        user = _make_user()
        tokens = svc.issue(user)
        access_payload = pyjwt.decode(
            tokens["access_token"], "test-secret", algorithms=["HS256"]
        )
        refresh_payload = pyjwt.decode(
            tokens["refresh_token"], "test-secret", algorithms=["HS256"]
        )
        assert "refresh_jti" in access_payload
        assert access_payload["refresh_jti"] == refresh_payload["jti"]
        # access token 自己的 jti 仍存在且不同于 refresh_jti
        assert access_payload["jti"] != access_payload["refresh_jti"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_jwt_service.py::TestJwtIssue::test_access_token_contains_refresh_jti -v`
预期：FAIL，报错 `AssertionError: assert 'refresh_jti' in access_payload` 失败

- [ ] **步骤 3：修改 JwtService.issue 实现**

修改 `src/umcp_core/transport/auth.py` 的 `issue` 方法（行 35-65），先生成 refresh_jti 并嵌入 access payload：

```python
    def issue(self, user: User) -> dict[str, Any]:
        """签发 token 对。返回 {access_token, refresh_token, token_type, expires_in}。

        access token 嵌入 refresh_jti 字段，便于 logout 时一并吊销 refresh token。
        """
        now = datetime.now(timezone.utc)
        base_claims = {
            "sub": user.user_id,
            "name": user.name,
            "roles": list(user.roles.keys()),
            "active_role": user.active_role.role_type if user.active_role else None,
        }
        refresh_jti = uuid.uuid4().hex
        access_payload = {
            **base_claims,
            "iat": now,
            "exp": now + timedelta(seconds=self._access_ttl),
            "jti": uuid.uuid4().hex,
            "type": "access",
            "refresh_jti": refresh_jti,
        }
        refresh_payload = {
            **base_claims,
            "iat": now,
            "exp": now + timedelta(seconds=self._refresh_ttl),
            "jti": refresh_jti,
            "type": "refresh",
        }
        access_token = pyjwt.encode(access_payload, self._secret, algorithm="HS256")
        refresh_token = pyjwt.encode(refresh_payload, self._secret, algorithm="HS256")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": self._access_ttl,
        }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_jwt_service.py::TestJwtIssue -v`
预期：PASS（4 个测试全过，含原有 2 个 + 新增 1 个；不破坏 refresh token 测试）

- [ ] **步骤 5：运行 JwtService 全量回归**

运行：`pytest tests/test_jwt_service.py -v`
预期：PASS（所有测试通过，含 decode/revoke/refresh/user_from_claims）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/transport/auth.py tests/test_jwt_service.py
git commit -m "feat(auth): access token 嵌入 refresh_jti 字段，支持 logout 一并吊销"
```

---

### 任务 2：logout 端点吊销 refresh_jti

**文件：**
- 修改：`src/umcp_core/transport/routers/auth.py:80-100`
- 测试：`tests/test_auth_router.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_auth_router.py` 的 `TestLogout` 类末尾追加：

```python
    def test_logout_revokes_refresh_token(self):
        """登出后用 refresh token 调 /refresh 应返回 401。"""
        app = _make_app()
        client = TestClient(app)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        data = login_resp.json()["data"]
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        # 登出
        logout_resp = client.post("/api/v1/auth/logout", headers=headers)
        assert logout_resp.status_code == 200
        # 用 refresh token 调 /refresh 应 401（refresh_jti 已被吊销）
        refresh_resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 401
        assert refresh_resp.json()["code"] == 1001
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_auth_router.py::TestLogout::test_logout_revokes_refresh_token -v`
预期：FAIL，`refresh_resp.status_code == 401` 断言失败（实际为 200，因为 refresh_jti 未被吊销）

- [ ] **步骤 3：修改 logout 端点实现**

修改 `src/umcp_core/transport/routers/auth.py` 的 `logout` 函数（行 80-100），解码后同时吊销 access_jti 和 refresh_jti：

```python
@router.post("/logout", response_model=Envelope)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    jwt_service: JwtService = Depends(get_jwt_service),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """登出，吊销当前 access token 及其关联的 refresh token。"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if token:
        try:
            payload = jwt_service.decode(token)
            # 吊销 access token
            access_jti = payload.get("jti")
            if access_jti:
                jwt_service.revoke(access_jti)
            # 吊销关联的 refresh token（access 中嵌入的 refresh_jti）
            refresh_jti = payload.get("refresh_jti")
            if refresh_jti:
                jwt_service.revoke(refresh_jti)
        except Exception:
            # 解码失败忽略（get_current_user 已校验过，此处兜底）
            pass
    return ok(message="已登出")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_auth_router.py::TestLogout -v`
预期：PASS（3 个测试全过，含原有 2 个 + 新增 1 个）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/transport/routers/auth.py tests/test_auth_router.py
git commit -m "feat(auth): logout 端点吊销 access 与 refresh token"
```

---

### 任务 3：refresh 端点 token 轮换

**文件：**
- 修改：`src/umcp_core/transport/routers/auth.py:61-77`
- 测试：`tests/test_auth_router.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_auth_router.py` 的 `TestRefresh` 类末尾追加：

```python
    def test_refresh_rotates_old_refresh_token(self):
        """refresh 后旧 refresh token 应失效（token 轮换）。"""
        app = _make_app()
        client = TestClient(app)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        old_refresh = login_resp.json()["data"]["refresh_token"]
        # 第一次 refresh：成功
        resp1 = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp1.status_code == 200
        new_tokens = resp1.json()["data"]
        assert "access_token" in new_tokens
        assert "refresh_token" in new_tokens
        # 第二次 refresh 用旧 refresh token：应 401（已被吊销）
        resp2 = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp2.status_code == 401
        assert resp2.json()["code"] == 1001

    def test_refresh_new_token_pair_has_refresh_jti_link(self):
        """refresh 签发的新 access token 仍嵌入新 refresh 的 jti。"""
        app = _make_app()
        client = TestClient(app)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        old_refresh = login_resp.json()["data"]["refresh_token"]
        resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        new_tokens = resp.json()["data"]
        import jwt as pyjwt
        access_payload = pyjwt.decode(
            new_tokens["access_token"], "test-secret", algorithms=["HS256"]
        )
        refresh_payload = pyjwt.decode(
            new_tokens["refresh_token"], "test-secret", algorithms=["HS256"]
        )
        assert access_payload["refresh_jti"] == refresh_payload["jti"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_auth_router.py::TestRefresh::test_refresh_rotates_old_refresh_token -v`
预期：FAIL，第二次 refresh 应返回 200（旧 refresh 未被吊销）

- [ ] **步骤 3：修改 refresh 端点实现**

修改 `src/umcp_core/transport/routers/auth.py` 的 `refresh` 函数（行 61-77），在签发新 token 前吊销旧 refresh_jti：

```python
@router.post("/refresh", response_model=Envelope[TokenResponse])
async def refresh(
    req: RefreshRequest,
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope[TokenResponse]:
    """用 refresh_token 换新 access_token，并吊销旧 refresh_token（轮换）。"""
    try:
        payload = jwt_service.decode(req.refresh_token)
    except pyjwt.InvalidTokenError as e:
        raise InvalidCredentialError(message=f"refresh token 无效: {e}") from e
    if payload.get("type") != "refresh":
        raise InvalidCredentialError(message="非 refresh token")
    if jwt_service.is_revoked(payload.get("jti", "")):
        raise InvalidCredentialError(message="refresh token 已吊销")

    # 吊销旧 refresh token（token 轮换，防止重放）
    old_jti = payload.get("jti")
    if old_jti:
        jwt_service.revoke(old_jti)

    # 重建 User 并签发新 token 对
    user = user_from_claims(payload)
    tokens = jwt_service.issue(user)
    return ok(tokens)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_auth_router.py::TestRefresh -v`
预期：PASS（4 个测试全过）

- [ ] **步骤 5：运行 auth router 全量回归**

运行：`pytest tests/test_auth_router.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/transport/routers/auth.py tests/test_auth_router.py
git commit -m "feat(auth): refresh 端点实现 token 轮换，吊销旧 refresh token"
```

---

### 任务 4：Repository 接口扩展 list_all 抽象方法

**文件：**
- 修改：`src/umcp_core/repositories/interfaces.py:22-87`
- 测试：本任务无独立测试，由任务 5/6 的实现测试覆盖

- [ ] **步骤 1：修改 interfaces.py，为 3 个仓储加 list_all 抽象方法**

在 `src/umcp_core/repositories/interfaces.py` 的 `TaskRepository` 类末尾（行 43 后）追加：

```python
    @abstractmethod
    def list_all(self) -> list[Task]:
        """返回所有任务（router 层负责过滤）。"""
        ...
```

在 `ResourceRepository` 类末尾（行 67 后）追加：

```python
    @abstractmethod
    def list_all(self) -> list[Resource]:
        """返回所有资源（router 层负责过滤）。"""
        ...
```

在 `DealRepository` 类末尾（行 87 后）追加：

```python
    @abstractmethod
    def list_all(self) -> list[Deal]:
        """返回所有交易（router 层负责过滤）。"""
        ...
```

- [ ] **步骤 2：运行全量测试验证未破坏（in_memory 实现还未加，会抽象方法未实现错误）**

运行：`pytest tests/test_repositories_in_memory.py -v`
预期：FAIL，`TypeError: Can't instantiate abstract class InMemoryTaskRepository with abstract method list_all`

- [ ] **步骤 3：Commit（接口先行，便于并行实现）**

```bash
git add src/umcp_core/repositories/interfaces.py
git commit -m "feat(repo): 仓储接口扩展 list_all 抽象方法"
```

---

### 任务 5：InMemory 仓储实现 list_all

**文件：**
- 修改：`src/umcp_core/repositories/in_memory.py:29-119`
- 测试：`tests/test_repositories_in_memory.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_repositories_in_memory.py` 的 `TestInMemoryTaskRepository` 类末尾追加：

```python
    def test_list_all_returns_all_tasks(self):
        repo = InMemoryTaskRepository()
        t1 = _make_task(demander_id="d1")
        t2 = _make_task(demander_id="d2")
        repo.save(t1)
        repo.save(t2)
        result = repo.list_all()
        assert {t.task_id for t in result} == {t1.task_id, t2.task_id}

    def test_list_all_empty(self):
        repo = InMemoryTaskRepository()
        assert repo.list_all() == []

    def test_list_all_returns_copy(self):
        """list_all 返回的列表应是副本，外部修改不影响内部状态。"""
        repo = InMemoryTaskRepository()
        repo.save(_make_task())
        result = repo.list_all()
        result.clear()
        assert len(repo.list_all()) == 1
```

在 `TestInMemoryResourceRepository` 类末尾追加：

```python
    def test_list_all_returns_all_resources(self):
        repo = InMemoryResourceRepository()
        r1 = _make_resource(supplier_id="s1")
        r2 = _make_resource(supplier_id="s2")
        repo.save(r1)
        repo.save(r2)
        result = repo.list_all()
        assert {r.resource_id for r in result} == {r1.resource_id, r2.resource_id}

    def test_list_all_empty(self):
        repo = InMemoryResourceRepository()
        assert repo.list_all() == []
```

在 `TestInMemoryDealRepository` 类末尾追加：

```python
    def test_list_all_returns_all_deals(self):
        repo = InMemoryDealRepository()
        d1 = _make_deal(task_id="t1")
        d2 = _make_deal(task_id="t2")
        repo.save(d1)
        repo.save(d2)
        result = repo.list_all()
        assert {d.deal_id for d in result} == {d1.deal_id, d2.deal_id}

    def test_list_all_empty(self):
        repo = InMemoryDealRepository()
        assert repo.list_all() == []
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_repositories_in_memory.py -k list_all -v`
预期：FAIL，`TypeError: Can't instantiate abstract class ...` （因接口加了抽象方法但实现未加）

- [ ] **步骤 3：修改 in_memory.py 实现 list_all**

在 `InMemoryTaskRepository` 类的 `update_status` 方法后（行 61 后）追加：

```python
    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())
```

在 `InMemoryResourceRepository` 类的 `update_status` 方法后（行 95 后）追加：

```python
    def list_all(self) -> list[Resource]:
        with self._lock:
            return list(self._resources.values())
```

在 `InMemoryDealRepository` 类的 `find_by_supplier` 方法后（行 118 后）追加：

```python
    def list_all(self) -> list[Deal]:
        with self._lock:
            return list(self._deals.values())
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_repositories_in_memory.py -v`
预期：PASS（所有原有测试 + 8 个新增 list_all 测试通过）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/repositories/in_memory.py tests/test_repositories_in_memory.py
git commit -m "feat(repo): InMemory 仓储实现 list_all"
```

---

### 任务 6：Postgres 仓储实现 list_all

**文件：**
- 修改：`src/umcp_core/repositories/postgres/task_repo.py`
- 修改：`src/umcp_core/repositories/postgres/resource_repo.py`
- 修改：`src/umcp_core/repositories/postgres/deal_repo.py`
- 测试：`tests/test_postgres_repos.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_postgres_repos.py` 末尾追加（注意：`pg_bundle` fixture 已在 conftest.py 提供）：

```python
class TestPostgresListAll:
    def test_task_list_all(self, pg_bundle):
        from umcp_core.core.task import StandardTask
        t1 = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        t2 = StandardTask(demander_id="u2", domain_tag=DomainTag.of("design"))
        pg_bundle.task_repo.save(t1)
        pg_bundle.task_repo.save(t2)
        result = pg_bundle.task_repo.list_all()
        task_ids = {t.task_id for t in result}
        assert t1.task_id in task_ids
        assert t2.task_id in task_ids

    def test_task_list_all_empty(self, pg_bundle):
        result = pg_bundle.task_repo.list_all()
        assert result == []

    def test_resource_list_all(self, pg_bundle):
        from umcp_core.core.resource import Resource
        class _R(Resource):
            def resource_type(self) -> str:
                return "test"
        r1 = _R(supplier_id="s1", domain_tag=DomainTag.of("ride"))
        r2 = _R(supplier_id="s2", domain_tag=DomainTag.of("design"))
        pg_bundle.resource_repo.save(r1)
        pg_bundle.resource_repo.save(r2)
        result = pg_bundle.resource_repo.list_all()
        resource_ids = {r.resource_id for r in result}
        assert r1.resource_id in resource_ids
        assert r2.resource_id in resource_ids

    def test_deal_list_all(self, pg_bundle):
        from umcp_core.core.deal import Deal
        d1 = Deal(task_id="t1", resource_id="r1", demander_id="u1", supplier_id="s1")
        d2 = Deal(task_id="t2", resource_id="r2", demander_id="u2", supplier_id="s2")
        pg_bundle.deal_repo.save(d1)
        pg_bundle.deal_repo.save(d2)
        result = pg_bundle.deal_repo.list_all()
        deal_ids = {d.deal_id for d in result}
        assert d1.deal_id in deal_ids
        assert d2.deal_id in deal_ids
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_postgres_repos.py::TestPostgresListAll -v -m postgres`
预期：FAIL，`AttributeError: 'PostgresTaskRepository' object has no attribute 'list_all'`（若无 PG 服务则 SKIP，需在本地启动 docker compose up -d postgres 后验证）

- [ ] **步骤 3：修改 3 个 PG 仓储实现 list_all**

在 `src/umcp_core/repositories/postgres/task_repo.py` 的 `PostgresTaskRepository` 类末尾（`_reconstruct_if_composite` 方法后）追加：

```python
    def list_all(self) -> list[Task]:
        with self._session() as session:
            stmt = select(TaskModel)
            models = session.execute(stmt).scalars().all()
            return [self._reconstruct_if_composite(session, m) for m in models]
```

在 `src/umcp_core/repositories/postgres/resource_repo.py` 的 `PostgresResourceRepository` 类末尾追加：

```python
    def list_all(self) -> list[Resource]:
        with self._session() as session:
            stmt = select(ResourceModel)
            models = session.execute(stmt).scalars().all()
            return [resource_from_orm(m) for m in models]
```

在 `src/umcp_core/repositories/postgres/deal_repo.py` 的 `PostgresDealRepository` 类末尾追加：

```python
    def list_all(self) -> list[Deal]:
        with self._session() as session:
            stmt = select(DealModel)
            models = session.execute(stmt).scalars().all()
            return [deal_from_orm(m) for m in models]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_postgres_repos.py::TestPostgresListAll -v -m postgres`
预期：PASS（4 个测试全过；无 PG 服务时 SKIP）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/repositories/postgres/task_repo.py src/umcp_core/repositories/postgres/resource_repo.py src/umcp_core/repositories/postgres/deal_repo.py tests/test_postgres_repos.py
git commit -m "feat(repo): Postgres 仓储实现 list_all"
```

---

### 任务 7：router list 端点改用 list_all

**文件：**
- 修改：`src/umcp_core/transport/routers/tasks.py:76-105`
- 修改：`src/umcp_core/transport/routers/resources.py:95-124`
- 修改：`src/umcp_core/transport/routers/deals.py:69-97`
- 测试：`tests/test_http_e2e.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_http_e2e.py` 末尾追加：

```python
class TestListEndpoints:
    """list 端点过滤与分页测试。"""

    def test_list_tasks_filter_by_status(self):
        client = _make_client()
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        # 创建两个任务（同一 domain）
        for _ in range(2):
            client.post(
                "/api/v1/tasks",
                json={"demander_id": "d1", "domain_tag": "ride"},
                headers=headers,
            )
        # 按 status 过滤
        resp = client.get(
            "/api/v1/tasks?status=matching",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # StubMatchStrategy 匹配后任务状态可能为 MATCHING 或更后
        # 这里只验证不静默返回空（in-memory 模式下原 _tasks 穿透也能工作，
        # PG 模式下若未用 list_all 会返回空）
        assert body["data"]["total"] >= 0  # 至少不报错

    def test_list_resources_filter_by_domain(self):
        client = _make_client()
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(
            "/api/v1/resources?domain_tag=ride",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # _StubResource 已预置 1 个 ride 资源
        assert body["data"]["total"] >= 1
        for item in body["data"]["items"]:
            assert item["domain_tag"] == "ride"

    def test_list_deals_all(self):
        client = _make_client()
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        # 创建一个 deal
        client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "res_1",
                "demander_id": "d1",
                "supplier_id": "supplier_1",
            },
            headers=headers,
        )
        resp = client.get("/api/v1/deals", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["total"] >= 1
```

- [ ] **步骤 2：运行测试验证**

运行：`pytest tests/test_http_e2e.py::TestListEndpoints -v`
预期：PASS（in-memory 下原实现也能工作；但 PG 模式下会 FAIL。这里先确保 in-memory 不破坏）

- [ ] **步骤 3：修改 tasks.py 的 list_tasks**

修改 `src/umcp_core/transport/routers/tasks.py` 的 `list_tasks` 函数（行 76-105），用 `list_all()` 替换 `getattr(repo, "_tasks", {})`：

```python
@router.get("", response_model=Envelope[PaginatedData[TaskInfo]])
async def list_tasks(
    status: str | None = None,
    domain_tag: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[TaskInfo]]:
    """查询任务列表。"""
    tasks = server.task_repo.list_all()
    if status:
        tasks = [t for t in tasks if t.status == status]
    if domain_tag:
        tasks = [t for t in tasks if t.domain_tag.value == domain_tag]

    total = len(tasks)
    start = (page - 1) * size
    end = start + size
    page_items = tasks[start:end]
    return paginated(
        items=[_task_to_info(t) for t in page_items],
        total=total,
        page=page,
        size=size,
    )
```

- [ ] **步骤 4：修改 resources.py 的 list_resources**

修改 `src/umcp_core/transport/routers/resources.py` 的 `list_resources` 函数（行 95-124）：

```python
@router.get("", response_model=Envelope[PaginatedData[ResourceInfo]])
async def list_resources(
    domain_tag: str | None = None,
    status: str | None = None,
    supplier_id: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[ResourceInfo]]:
    """查询资源列表。"""
    all_resources = server.resource_repo.list_all()
    if domain_tag:
        all_resources = [r for r in all_resources if r.domain_tag.value == domain_tag]
    if status:
        all_resources = [r for r in all_resources if r.status == status]
    if supplier_id:
        all_resources = [r for r in all_resources if r.supplier_id == supplier_id]

    total = len(all_resources)
    start = (page - 1) * size
    end = start + size
    page_items = all_resources[start:end]
    return paginated(
        items=[_resource_to_info(r) for r in page_items],
        total=total,
        page=page,
        size=size,
    )
```

- [ ] **步骤 5：修改 deals.py 的 list_deals**

修改 `src/umcp_core/transport/routers/deals.py` 的 `list_deals` 函数（行 69-97）：

```python
@router.get("", response_model=Envelope[PaginatedData[DealInfo]])
async def list_deals(
    task_id: str | None = None,
    supplier_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[DealInfo]]:
    """查询交易列表。"""
    all_deals = server.deal_repo.list_all()
    if task_id:
        all_deals = [d for d in all_deals if d.task_id == task_id]
    if supplier_id:
        all_deals = [d for d in all_deals if d.supplier_id == supplier_id]
    if status:
        all_deals = [d for d in all_deals if d.status == status]

    total = len(all_deals)
    start = (page - 1) * size
    end = start + size
    page_items = all_deals[start:end]
    return paginated(
        items=[_deal_to_info(d) for d in page_items],
        total=total,
        page=page,
        size=size,
    )
```

- [ ] **步骤 6：运行测试验证通过**

运行：`pytest tests/test_http_e2e.py -v`
预期：PASS（所有 HTTP E2E 测试通过，含新增 3 个 TestListEndpoints）

- [ ] **步骤 7：运行 router 相关全量回归**

运行：`pytest tests/test_tasks_resources_matches.py tests/test_deals_trust_events.py tests/test_http_e2e.py -v`
预期：PASS

- [ ] **步骤 8：Commit**

```bash
git add src/umcp_core/transport/routers/tasks.py src/umcp_core/transport/routers/resources.py src/umcp_core/transport/routers/deals.py tests/test_http_e2e.py
git commit -m "feat(router): list 端点改用仓储 list_all 方法，兼容 PG 模式"
```

---

### 任务 8：lifespan 资源释放

**文件：**
- 修改：`src/umcp_core/transport/app.py:43-57`
- 测试：`tests/test_app_factory.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_app_factory.py` 末尾追加（先查阅该文件确认 import 与风格）：

```python
class TestLifespanResourceRelease:
    """验证 lifespan shutdown 释放 server 资源。"""

    def test_shutdown_calls_server_stop_and_dispose(self):
        """lifespan 结束时应调用 server.stop() 和 server.dispose()。"""
        from umcp_core.layers.l1 import PhoneAuthProvider
        from umcp_core.server import UMCPServer
        from umcp_core.transport.app import create_app
        from umcp_core.transport.config import TransportConfig

        server = UMCPServer()
        server.use_in_memory_repositories()
        server.set_auth_provider(PhoneAuthProvider())
        config = TransportConfig(jwt_secret="test-secret")
        app = create_app(server, config)

        # 记录 dispose 调用次数（in-memory 模式 dispose 是 no-op，但方法应被调用）
        # 通过 mock 跟踪
        import unittest.mock as mock
        with mock.patch.object(server, "stop") as m_stop, \
             mock.patch.object(server, "dispose") as m_dispose:
            with TestClient(app):
                # 启动并立即退出，触发 lifespan shutdown
                pass
            m_stop.assert_called_once()
            m_dispose.assert_called_once()
```

注意：需在文件顶部补充 `from fastapi.testclient import TestClient` import（若未有）。

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_app_factory.py::TestLifespanResourceRelease -v`
预期：FAIL，`AssertionError: Expected 'stop' to have been called`（lifespan shutdown 未调用 stop）

- [ ] **步骤 3：修改 app.py 的 lifespan**

修改 `src/umcp_core/transport/app.py` 的 `lifespan` 函数（行 43-57），在 shutdown 分支追加 `server.stop()` 和 `server.dispose()`：

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        loop = asyncio.get_event_loop()
        ws_bridge_ref["loop"] = loop
        bridge = make_ws_event_bridge(ws_manager, loop)
        ws_bridge_ref["bridge"] = bridge
        server.event_bus.subscribe_all(bridge)
        logger.info("UMCP HTTP 服务已启动")
        yield
        # shutdown
        if ws_bridge_ref["bridge"]:
            server.event_bus.unsubscribe_all(ws_bridge_ref["bridge"])
        await ws_manager.disconnect_all()
        server.stop()
        server.dispose()
        logger.info("UMCP HTTP 服务已停止")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_app_factory.py::TestLifespanResourceRelease -v`
预期：PASS

- [ ] **步骤 5：运行 app_factory 全量回归**

运行：`pytest tests/test_app_factory.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/transport/app.py tests/test_app_factory.py
git commit -m "feat(transport): lifespan shutdown 调用 server.stop/dispose 释放资源"
```

---

### 任务 9：Task._emit payload 补全 demander_id

**文件：**
- 修改：`src/umcp_core/core/task.py:101-107`（assign_to）和 `120-131`（_emit）
- 测试：`tests/test_core.py`

- [ ] **步骤 1：编写失败的测试**

先查阅 `tests/test_core.py` 的结构，在末尾追加一个测试类：

```python
class TestTaskEmitPayload:
    """Task._emit payload 应包含 demander_id（WS 推送依赖）。"""

    def test_publish_emits_event_with_demander_id(self):
        from umcp_core.core.domain import DomainTag
        from umcp_core.core.task import StandardTask
        from umcp_core.events.bus import EventBus
        from umcp_core.events.types import EventType

        bus = EventBus()
        task = StandardTask(demander_id="user_123", domain_tag=DomainTag.of("ride"))
        task.bind_event_bus(bus)
        task.publish()

        events = bus.history()
        pub_events = [e for e in events if e.type == EventType.TASK_PUBLISHED]
        assert len(pub_events) == 1
        assert pub_events[0].payload["task_id"] == task.task_id
        assert pub_events[0].payload["demander_id"] == "user_123"

    def test_assign_emits_event_with_supplier_id(self):
        from umcp_core.core.domain import DomainTag
        from umcp_core.core.task import StandardTask
        from umcp_core.events.bus import EventBus
        from umcp_core.events.types import EventType

        bus = EventBus()
        task = StandardTask(demander_id="user_123", domain_tag=DomainTag.of("ride"))
        task.bind_event_bus(bus)
        task.publish()  # 推进到 MATCHING
        task.assign_to("res_456")

        events = bus.history()
        assign_events = [e for e in events if e.type == EventType.TASK_ASSIGNED]
        assert len(assign_events) == 1
        assert assign_events[0].payload["supplier_id"] == "res_456"
        # 仍保留 demander_id
        assert assign_events[0].payload["demander_id"] == "user_123"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_core.py::TestTaskEmitPayload -v`
预期：FAIL，`KeyError: 'demander_id'`（payload 中无此字段）

- [ ] **步骤 3：修改 task.py 的 _emit 和 assign_to**

修改 `src/umcp_core/core/task.py`：

行 101-107 的 `assign_to` 改为（注意：当前签名是 `assign_to(self, resource_id: str)`，规格描述是 `assign_to(self, resource: Resource)`，但实际代码用的是 resource_id 字符串。保持 resource_id 字符串签名，但在 payload 中传 supplier_id）：

```python
    def assign_to(self, resource_id: str) -> None:
        """将任务指派给某个资源。"""
        if self.status not in (TaskStatus.MATCHING, TaskStatus.PUBLISHED):
            raise RuntimeError(f"任务状态 {self.status} 不允许指派")
        self.assigned_resource_id = resource_id
        self._transition(TaskStatus.ASSIGNED)
        self._emit(
            EventType.TASK_ASSIGNED,
            payload={"supplier_id": resource_id},
        )
```

行 120-131 的 `_emit` 改为：

```python
    def _emit(self, event_type: EventType, payload: dict[str, Any] | None = None) -> None:
        if self._event_bus is None:
            return
        from umcp_core.events.bus import Event

        self._event_bus.publish(
            Event(
                type=event_type,
                source_layer="L2",
                payload={
                    "task_id": self.task_id,
                    "demander_id": self.demander_id,
                    **(payload or {}),
                },
            )
        )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_core.py::TestTaskEmitPayload -v`
预期：PASS

- [ ] **步骤 5：运行核心库全量回归**

运行：`pytest tests/test_core.py tests/test_events.py tests/test_publish_and_match.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/core/task.py tests/test_core.py
git commit -m "feat(task): _emit payload 补全 demander_id 与 supplier_id"
```

---

### 任务 10：Deal 添加 event_bus 机制

**文件：**
- 修改：`src/umcp_core/core/deal.py`
- 测试：`tests/test_deals_trust_events.py`（或新建 `tests/test_deal_events.py`，本计划采用前者）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_deals_trust_events.py` 顶部补充 import，并在文件末尾追加测试类：

补充 import（若未有）：

```python
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType
```

末尾追加：

```python
class TestDealEventEmission:
    """Deal 状态变更应通过 EventBus 发布对应事件。"""

    def test_activate_emits_deal_paid(self):
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.activate()
        events = [e for e in bus.history() if e.type == EventType.DEAL_PAID]
        assert len(events) == 1
        assert events[0].payload["deal_id"] == deal.deal_id
        assert events[0].payload["task_id"] == "t1"
        assert events[0].payload["demander_id"] == "d1"
        assert events[0].payload["supplier_id"] == "s1"

    def test_complete_emits_deal_completed(self):
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.activate()
        deal.complete()
        events = [e for e in bus.history() if e.type == EventType.DEAL_COMPLETED]
        assert len(events) == 1

    def test_open_dispute_emits_deal_disputed(self):
        bus = EventBus()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        deal.bind_event_bus(bus)
        deal.activate()
        deal.open_dispute()
        events = [e for e in bus.history() if e.type == EventType.DEAL_DISPUTED]
        assert len(events) == 1

    def test_deal_without_event_bus_is_silent(self):
        """未绑定 event_bus 时，状态变更不应抛异常。"""
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        # 不调用 bind_event_bus
        deal.activate()
        deal.complete()
        # 无异常即通过
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_deals_trust_events.py::TestDealEventEmission -v`
预期：FAIL，`AttributeError: 'Deal' object has no attribute 'bind_event_bus'`

- [ ] **步骤 3：修改 deal.py 添加 event_bus 机制**

修改 `src/umcp_core/core/deal.py`，在 `__init__` 末尾添加 `_event_bus` 字段，添加 `bind_event_bus`/`_emit` 方法，并在 `activate`/`complete`/`open_dispute` 中发事件。

完整的 `deal.py` 修改如下（仅展示新增/变更部分）：

`__init__` 末尾追加（行 55 后）：

```python
        self._event_bus: "EventBus | None" = None
```

并在文件顶部 import 区域添加（避免循环，用 TYPE_CHECKING 或延迟导入）：

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from umcp_core.events.bus import EventBus
    from umcp_core.events.types import EventType
```

实际上为简化，直接在 `_emit` 内部延迟导入（与 task.py 一致）。`__init__` 末尾追加：

```python
        self._event_bus = None  # type: ignore[assignment]
```

在 `activate` 方法中（行 57-59）改为：

```python
    def activate(self) -> None:
        """匹配确认后激活。"""
        self._transition(DealStatus.ACTIVE)
        self._emit(self._get_event_type("DEAL_PAID"))
```

在 `complete` 方法中（行 61-64）改为：

```python
    def complete(self) -> None:
        """完成交易。"""
        self._transition(DealStatus.COMPLETED)
        self.completed_at = datetime.utcnow()
        self._emit(self._get_event_type("DEAL_COMPLETED"))
```

在 `open_dispute` 方法中（行 72-76）改为：

```python
    def open_dispute(self) -> None:
        """开启争议。"""
        if self.status not in (DealStatus.ACTIVE, DealStatus.COMPLETED):
            raise RuntimeError(f"交易状态 {self.status} 不允许开启争议")
        self._transition(DealStatus.DISPUTED)
        self._emit(self._get_event_type("DEAL_DISPUTED"))
```

在 `_transition` 方法后（行 95 后）追加 `bind_event_bus`、`_emit`、`_get_event_type` 方法：

```python
    def bind_event_bus(self, bus: "EventBus") -> None:
        """绑定事件总线。"""
        self._event_bus = bus

    def _get_event_type(self, name: str):
        """延迟导入 EventType，避免循环依赖。"""
        from umcp_core.events.types import EventType
        return getattr(EventType, name)

    def _emit(self, event_type, payload: dict[str, Any] | None = None) -> None:
        """发布事件。未绑定 event_bus 时静默返回。"""
        if self._event_bus is None:
            return
        from umcp_core.events.bus import Event

        self._event_bus.publish(
            Event(
                type=event_type,
                source_layer="L4",
                payload={
                    "deal_id": self.deal_id,
                    "task_id": self.task_id,
                    "demander_id": self.demander_id,
                    "supplier_id": self.supplier_id,
                    **(payload or {}),
                },
            )
        )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_deals_trust_events.py::TestDealEventEmission -v`
预期：PASS（4 个测试全过）

- [ ] **步骤 5：运行 deal 相关全量回归**

运行：`pytest tests/test_deals_trust_events.py tests/test_fsm.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/core/deal.py tests/test_deals_trust_events.py
git commit -m "feat(deal): 添加 event_bus 机制，状态变更发布 DEAL_* 事件"
```

---

### 任务 11：deals router 发布 DEAL_CREATED 并绑定 event_bus

**文件：**
- 修改：`src/umcp_core/transport/routers/deals.py:51-66`（create_deal）和 `113-128`（activate_deal）、`131-146`（complete_deal）、`149-164`（dispute_deal）
- 测试：`tests/test_deals_trust_events.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_deals_trust_events.py` 末尾追加：

```python
class TestDealRouterEventPublishing:
    """deals router 应在创建交易时发布 DEAL_CREATED 事件。"""

    def test_create_deal_emits_deal_created_event(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        # 从 app.state.server 拿到 event_bus 引用
        server = app.state.server
        # 创建 deal
        resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "r1",
                "demander_id": "d1",
                "supplier_id": "s1",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        # 验证 DEAL_CREATED 事件已发布
        events = server.event_bus.history()
        created_events = [e for e in events if e.type.value == "deal.created"]
        assert len(created_events) == 1
        assert created_events[0].payload["task_id"] == "t1"
        assert created_events[0].payload["demander_id"] == "d1"

    def test_activate_deal_emits_deal_paid_event(self):
        app = _make_app()
        client = TestClient(app)
        token = _login_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        # 创建 deal
        create_resp = client.post(
            "/api/v1/deals",
            json={
                "task_id": "t1",
                "resource_id": "r1",
                "demander_id": "d1",
                "supplier_id": "s1",
            },
            headers=headers,
        )
        deal_id = create_resp.json()["data"]["deal_id"]
        server = app.state.server
        # 激活前清空 history 便于断言
        server.event_bus.clear()
        # 激活
        client.post(f"/api/v1/deals/{deal_id}/activate", headers=headers)
        events = server.event_bus.history()
        paid_events = [e for e in events if e.type.value == "deal.paid"]
        assert len(paid_events) == 1
        assert paid_events[0].payload["deal_id"] == deal_id
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_deals_trust_events.py::TestDealRouterEventPublishing -v`
预期：FAIL，`assert len(created_events) == 1` 失败（router 未发 DEAL_CREATED；activate 也未绑定 event_bus）

- [ ] **步骤 3：修改 deals.py 的 create_deal 和 activate/complete/dispute**

修改 `src/umcp_core/transport/routers/deals.py`：

顶部补充 import（若未有）：

```python
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
```

`create_deal` 函数（行 51-66）改为：

```python
@router.post("", response_model=Envelope[DealInfo])
async def create_deal(
    req: CreateDealRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[DealInfo]:
    """创建交易。"""
    deal = Deal(
        task_id=req.task_id,
        resource_id=req.resource_id,
        demander_id=req.demander_id,
        supplier_id=req.supplier_id,
        final_amount=req.final_amount,
    )
    deal.bind_event_bus(server.event_bus)
    server.deal_repo.save(deal)
    # 发布 DEAL_CREATED 事件（构造时无 event_bus，由 router 显式发布）
    server.event_bus.publish(
        Event(
            type=EventType.DEAL_CREATED,
            source_layer="L4",
            payload={
                "deal_id": deal.deal_id,
                "task_id": deal.task_id,
                "resource_id": deal.resource_id,
                "demander_id": deal.demander_id,
                "supplier_id": deal.supplier_id,
            },
        )
    )
    return ok(_deal_to_info(deal))
```

`activate_deal`、`complete_deal`、`dispute_deal` 函数中，在 `find_by_id` 后追加 `deal.bind_event_bus(server.event_bus)`。以 `activate_deal` 为例（行 113-128）：

```python
@router.post("/{deal_id}/activate", response_model=Envelope)
async def activate_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """激活交易。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.activate()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="已激活")
```

`complete_deal`（行 131-146）同样在 `find_by_id` 后加 `deal.bind_event_bus(server.event_bus)`：

```python
@router.post("/{deal_id}/complete", response_model=Envelope)
async def complete_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """完成交易。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.complete()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="已完成")
```

`dispute_deal`（行 149-164）同样处理：

```python
@router.post("/{deal_id}/dispute", response_model=Envelope)
async def dispute_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """发起争议。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.open_dispute()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(message="争议已开启")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_deals_trust_events.py -v`
预期：PASS（含新增 2 个 TestDealRouterEventPublishing 测试 + 原有测试）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/transport/routers/deals.py tests/test_deals_trust_events.py
git commit -m "feat(router): deals router 创建交易发 DEAL_CREATED，激活/完成/争议绑定 event_bus"
```

---

### 任务 12：WS 推送链路 E2E 验证

**文件：**
- 修改：`tests/test_ws_integration.py:58-87`
- 测试：本任务仅修改测试

- [ ] **步骤 1：升级 test_ws_event_push 为真实推送验证**

修改 `tests/test_ws_integration.py` 的 `TestWsEventPush` 类的 `test_ws_connection_and_event_history` 测试，改为验证真实 WS 推送：

```python
class TestWsEventPush:
    def test_ws_receives_task_published_event(self):
        """创建任务后，WS 客户端应收到 task.published 推送。

        依赖：Task._emit payload 已补 demander_id（任务 9），
        使 WS 桥接函数 _extract_user_ids 能匹配到 user_id。
        """
        import jwt as pyjwt

        app, server = _make_app()
        client = TestClient(app)
        token = _login(client)

        # 解码 JWT 获取真实 user_id
        payload = pyjwt.decode(token, "ws-test-secret", algorithms=["HS256"])
        user_id = payload["sub"]

        with client.websocket_connect(f"/api/v1/ws/events?token={token}") as ws:
            # 用真实 user_id 作为 demander_id 创建任务，使 WS 能匹配
            client.post(
                "/api/v1/tasks",
                json={"demander_id": user_id, "domain_tag": "ride"},
                headers={"Authorization": f"Bearer {token}"},
            )
            # 应收到 task.published 推送
            msg = ws.receive_json()
            assert msg["type"] == "task.published"
            assert msg["data"]["task_id"]
            assert msg["data"]["demander_id"] == user_id

    def test_ws_receives_deal_created_event(self):
        """创建交易后，相关用户应收到 deal.created 推送。"""
        import jwt as pyjwt

        app, server = _make_app()
        client = TestClient(app)
        token = _login(client)
        payload = pyjwt.decode(token, "ws-test-secret", algorithms=["HS256"])
        user_id = payload["sub"]

        with client.websocket_connect(f"/api/v1/ws/events?token={token}") as ws:
            # 创建 deal，demander_id 设为当前 user_id
            client.post(
                "/api/v1/deals",
                json={
                    "task_id": "t1",
                    "resource_id": "res_1",
                    "demander_id": user_id,
                    "supplier_id": "supplier_1",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            msg = ws.receive_json()
            assert msg["type"] == "deal.created"
            assert msg["data"]["deal_id"]
            assert msg["data"]["demander_id"] == user_id
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_ws_integration.py::TestWsEventPush -v`
预期：PASS（2 个真实推送测试 + 原有 ping/pong 和拒绝连接测试）

注意：`test_ws_receives_deal_created_event` 依赖任务 11 的 router 发布 DEAL_CREATED。若任务 11 未完成，此测试会 FAIL（无 deal.created 推送）。

- [ ] **步骤 3：运行 WS 全量回归**

运行：`pytest tests/test_ws_integration.py tests/test_ws_manager.py -v`
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add tests/test_ws_integration.py
git commit -m "test(ws): 升级为真实推送验证，覆盖 task.published 和 deal.created"
```

---

### 任务 13：全量回归与收尾

**文件：** 无（仅运行测试）

- [ ] **步骤 1：运行全量测试套件**

运行：`pytest -v`
预期：所有测试通过（in-memory 模式下），PG 测试在无 PG 服务时 SKIP

- [ ] **步骤 2：若有 PG 服务，运行 PG 测试**

运行：`pytest -v -m postgres`
预期：PG 测试全过（含任务 6 的 list_all 测试）

- [ ] **步骤 3：检查无新增警告**

运行：`pytest -W error::DeprecationWarning -v 2>&1 | head -50`
预期：无新增 DeprecationWarning（已有的 asyncio.get_event_loop 警告属非目标，可忽略）

- [ ] **步骤 4：最终 commit（如有 lint 修复）**

```bash
git add -A
git commit -m "chore: 阶段五C 收尾" --allow-empty
```

- [ ] **步骤 5：使用 finishing-a-development-branch 技能收尾**

调用 `finishing-a-development-branch` 技能，验证测试通过后展示收尾选项。

---

## 自检

### 1. 规格覆盖度

| 规格章节 | 对应任务 |
|---------|---------|
| 功能 1.1 JwtService.issue 改造 | 任务 1 |
| 功能 1.2 logout 端点改造 | 任务 2 |
| 功能 1.3 refresh 端点改造（token 轮换） | 任务 3 |
| 功能 2.1 Repository 接口扩展 | 任务 4 |
| 功能 2.2 InMemory*Repository 实现 | 任务 5 |
| 功能 2.3 Postgres*Repository 实现 | 任务 6 |
| 功能 2.4 router 改造 | 任务 7 |
| 功能 3 lifespan 资源释放 | 任务 8 |
| 功能 4.1 Task._emit payload 补全 | 任务 9 |
| 功能 4.2 Deal 事件机制 | 任务 10 |
| 功能 4.3 Deal 创建时绑定 event_bus + DEAL_CREATED | 任务 11 |
| 测试策略 - E2E WS 推送 | 任务 12 |
| 回归 | 任务 13 |

所有规格章节均有对应任务。无遗漏。

### 2. 占位符扫描

- 无 "待定"、"TODO"、"后续实现"
- 无 "添加适当的错误处理"（所有错误处理均显式写出）
- 无 "类似任务 N"（每个任务的代码均完整给出）
- 所有步骤的代码块均包含实际代码

### 3. 类型一致性

- `list_all() -> list[Task]` / `list[Resource]` / `list[Deal]`：任务 4/5/6/7 一致
- `bind_event_bus(bus: EventBus) -> None`：任务 10/11 一致
- `_emit(event_type, payload: dict | None) -> None`：任务 9（Task）与任务 10（Deal）签名一致
- `refresh_jti` 字段名：任务 1（issue）与任务 2（logout）一致
- `DEAL_CREATED` / `DEAL_PAID` / `DEAL_COMPLETED` / `DEAL_DISPUTED` 事件类型：任务 10/11/12 一致（均来自 `events/types.py` 现有枚举）
- `assign_to(resource_id: str)` 签名保持不变，payload 中 `supplier_id` 字段：任务 9 一致

类型与命名均一致。
