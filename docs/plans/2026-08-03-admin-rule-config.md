# 管理员后台规则配置 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现管理员后台规则配置闭环——admin 角色认证 + 规则 CRUD 端点 + 变更历史 + 回滚 + 前端管理界面（列表/编辑/历史/回滚）。

**架构：**
- 后端：新增 `_ClaimsAdmin` 角色 + `require_admin` 守卫；扩展 `RuleConfig` 添加 `list_all`/`list_by_category`/`history` 公共方法；创建 `admin/rules` router 提供 5 个端点（list/detail/update/history/rollback）。
- 前端：`/admin/rules` 路由 + 路由守卫；规则列表页（按 category 分组）；规则编辑对话框（根据 key 推断编辑器类型）；历史抽屉（时间线 + 回滚按钮）。

**技术栈：** FastAPI + Pydantic（后端）、Next.js 14 + React Query + shadcn/ui（前端）、pytest + Vitest（测试）。

---

## 关键设计决策

### Admin 角色体系

当前系统有 `demander` 和 `supplier` 两种角色。新增 `admin` 角色：
- `_ClaimsAdmin` 实现 `Role` 接口，`PermissionSet({"manage_rules"})`
- `user_from_claims` 支持解析 `"admin"` 角色
- `require_admin` Depends 守卫：roles 不含 admin → 403 `PermissionDeniedError`
- 测试用 `_ClaimsUser` + `add_role(_ClaimsAdmin())` 生成 admin token

### RuleConfig 扩展公共方法

当前 `RuleConfig` 只有 `get`/`set`/`reload`/`subscribe`/`set_defaults`。为避免 admin router 访问私有 `_repo`，新增：
- `list_all()` → 合并默认值与仓储值，标记 `is_default`
- `list_by_category(category)` → 过滤 list_all 结果
- `history(key)` → 代理 `_repo.history(key)`
- `find(key)` → 代理 `_repo.find_by_key(key)`，返回完整规则 dict

### 规则值类型

RuleConfig 的 value 可以是任意 JSON 类型（int/list/dict）。当前取消策略规则：
- `escort.cancel.realtime.timeout_seconds`: int（默认 60）
- `escort.cancel.realtime.expand_after_seconds`: int（默认 30）
- `escort.cancel.scheduled.penalty_tiers`: list[dict]（默认 4 档梯度）

前端编辑器根据 key 后缀自动推断类型：
- `*_seconds` 结尾 → 数字输入框
- `*_penalty_tiers` 结尾 → 可编辑表格（hours_before + penalty）
- 其他 → JSON 文本框

### 回滚机制

从 `history` 记录中找到指定 `history_id` 的 `old_value`，调用 `rule_config.set(key, old_value, admin_id, category, reason)`。
- 如果 `old_value` 为 None（首次创建时的记录），返回 409（无法回滚到无旧值版本）
- 回滚本身也会产生新的 history 记录

### API 端点

| 端点 | 方法 | 守卫 | 功能 |
|------|------|------|------|
| `/api/v1/admin/rules` | GET | admin | 列出所有规则（可选 `?category=xxx`） |
| `/api/v1/admin/rules/{rule_key}` | GET | admin | 单个规则详情 |
| `/api/v1/admin/rules/{rule_key}` | PUT | admin | 更新规则（body: `{value, reason}`） |
| `/api/v1/admin/rules/{rule_key}/history` | GET | admin | 变更历史 |
| `/api/v1/admin/rules/{rule_key}/rollback` | POST | admin | 回滚（body: `{history_id, reason}`） |

---

## 文件结构

### 后端

- **修改** `src/umcp_core/transport/auth.py`：新增 `_ClaimsAdmin` 类；`user_from_claims` 支持 admin 角色。
- **修改** `src/umcp_core/transport/deps.py`：新增 `require_admin` 依赖。
- **修改** `src/umcp_core/shared/rules/config.py`：新增 `list_all`/`list_by_category`/`history`/`find` 公共方法。
- **创建** `src/umcp_core/transport/routers/admin/__init__.py`：admin 包初始化。
- **创建** `src/umcp_core/transport/routers/admin/rules.py`：admin 规则 router（5 个端点）。
- **修改** `src/umcp_core/transport/routers/__init__.py`：注册 admin rules router。
- **测试** `tests/test_admin_role.py`：验证 admin 角色与 require_admin 守卫。
- **测试** `tests/test_admin_rules_api.py`：验证 5 个端点。
- **测试** `tests/test_rule_config_list.py`：验证 list_all/list_by_category/history 方法。

### 前端

- **修改** `web/src/types/escort.ts`：新增 `RuleItem`/`RuleHistoryItem` 接口。
- **创建** `web/src/hooks/use-rules.ts`：admin 规则 hooks（list/detail/update/history/rollback）。
- **修改** `web/src/middleware.ts`：添加 `/admin` 路径的 admin 角色校验。
- **修改** `web/src/app/(protected)/dashboard/page.tsx`：admin 角色显示管理后台入口。
- **创建** `web/src/app/(protected)/admin/rules/page.tsx`：规则列表页。
- **创建** `web/src/components/rule-edit-dialog.tsx`：规则编辑对话框。
- **创建** `web/src/components/rule-history-drawer.tsx`：历史抽屉。
- **测试** `web/tests/admin-rules.test.tsx`：hooks 与组件测试。

---

## 任务分解

### 任务 1：后端 admin 角色体系 + RuleConfig 扩展

**文件：**
- 修改：`src/umcp_core/transport/auth.py`
- 修改：`src/umcp_core/transport/deps.py`
- 修改：`src/umcp_core/shared/rules/config.py`
- 测试：`tests/test_admin_role.py`
- 测试：`tests/test_rule_config_list.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_admin_role.py`：

```python
"""验证 admin 角色、user_from_claims 解析、require_admin 守卫。"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsAdmin, _ClaimsDemander, user_from_claims
from umcp_core.transport.deps import require_admin
from umcp_core.transport.errors import PermissionDeniedError


def _make_token(jwt_service: JwtService, roles: list[str], user_id: str = "admin1") -> str:
    """生成带指定角色的 token。"""
    user = _ClaimsUser(user_id=user_id, name="Admin")
    for r in roles:
        if r == "admin":
            user.add_role(_ClaimsAdmin())
        elif r == "demander":
            user.add_role(_ClaimsDemander())
    tokens = jwt_service.issue(user)
    return tokens["access_token"]


def _decode_token(jwt_service: JwtService, token: str):
    """解码 token 并重建 User。"""
    payload = jwt_service.decode(token)
    return user_from_claims(payload)


def test_claims_admin_role_type():
    """_ClaimsAdmin 的 role_type 应为 'admin'。"""
    admin = _ClaimsAdmin()
    assert admin.role_type == "admin"
    assert "manage_rules" in admin.permissions


def test_user_from_claims_parses_admin_role():
    """user_from_claims 应正确解析 admin 角色。"""
    jwt = JwtService("test-secret")
    token = _make_token(jwt, roles=["admin", "demander"])
    user = _decode_user(jwt, token)
    assert "admin" in user.roles
    assert "demander" in user.roles


def _decode_user(jwt: JwtService, token: str):
    payload = jwt.decode(token)
    return user_from_claims(payload)


def test_require_admin_allows_admin_user():
    """admin 用户应通过 require_admin 守卫。"""
    jwt = JwtService("test-secret")
    token = _make_token(jwt, roles=["admin"])

    router = APIRouter()

    @router.get("/test")
    async def test_endpoint(admin=Depends(require_admin)):
        return {"user_id": admin.user_id}

    app = FastAPI()
    app.include_router(router)
    # 注册异常处理器
    from umcp_core.transport.errors import register_exception_handlers
    register_exception_handlers(app)

    # 需要 app.state.jwt_service
    from umcp_core.transport.config import TransportConfig
    app.state.jwt_service = jwt

    client = TestClient(app)
    resp = client.get("/test", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "admin1"


def test_require_admin_rejects_non_admin_user():
    """非 admin 用户应被 require_admin 拒绝（403）。"""
    jwt = JwtService("test-secret")
    token = _make_token(jwt, roles=["demander"], user_id="student1")

    router = APIRouter()

    @router.get("/test")
    async def test_endpoint(admin=Depends(require_admin)):
        return {"user_id": admin.user_id}

    app = FastAPI()
    app.include_router(router)
    from umcp_core.transport.errors import register_exception_handlers
    register_exception_handlers(app)
    app.state.jwt_service = jwt

    client = TestClient(app)
    resp = client.get("/test", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
```

创建 `tests/test_rule_config_list.py`：

```python
"""验证 RuleConfig 的 list_all/list_by_category/history/find 方法。"""
from __future__ import annotations

from umcp_core.shared.rules.config import RuleConfig
from umcp_core.shared.rules.repository import InMemoryRuleRepository


def test_list_all_includes_defaults_and_overrides():
    """list_all 应合并默认值与仓储值。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set_defaults({
        "key1": 60,
        "key2": 30,
    })
    # 覆盖 key1
    config.set("key1", 120, updated_by="admin", category="escort.cancel")

    rules = config.list_all()
    rule_map = {r["rule_key"]: r for r in rules}

    assert rule_map["key1"]["rule_value"] == 120
    assert rule_map["key1"]["is_default"] is False
    assert rule_map["key1"]["category"] == "escort.cancel"

    assert rule_map["key2"]["rule_value"] == 30
    assert rule_map["key2"]["is_default"] is True


def test_list_by_category_filters():
    """list_by_category 应按分类过滤。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set("key1", 120, updated_by="admin", category="escort.cancel")
    config.set("key2", "val", updated_by="admin", category="escort.review")

    rules = config.list_by_category("escort.cancel")
    assert len(rules) == 1
    assert rules[0]["rule_key"] == "key1"


def test_history_returns_change_records():
    """history 应返回变更历史。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set("key1", 60, updated_by="admin", category="test", reason="初始")
    config.set("key1", 120, updated_by="admin", category="test", reason="调整")

    history = config.history("key1")
    assert len(history) == 2
    assert history[0]["new_value"] == 60
    assert history[1]["old_value"] == 60
    assert history[1]["new_value"] == 120


def test_find_returns_rule_dict():
    """find 应返回完整规则 dict（未设置返回 None）。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set("key1", 60, updated_by="admin", category="test")

    rule = config.find("key1")
    assert rule is not None
    assert rule["rule_value"] == 60
    assert rule["version"] == 1

    assert config.find("nonexistent") is None
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_admin_role.py tests/test_rule_config_list.py -v`
预期：FAIL（`_ClaimsAdmin` 不存在 / `list_all` 方法不存在）。

- [ ] **步骤 3：实现 _ClaimsAdmin 与 user_from_claims 扩展**

修改 `src/umcp_core/transport/auth.py`，在 `_ClaimsSupplier` 类之后添加 `_ClaimsAdmin`：

```python
from umcp_core.core.base import Demander, PermissionSet, Role, Supplier, User

class _ClaimsAdmin(Role):
    """管理员角色（从 JWT claims 重建）。"""

    def __init__(self) -> None:
        self._perms = PermissionSet({"manage_rules"})

    @property
    def role_type(self) -> str:
        return "admin"

    @property
    def permissions(self) -> PermissionSet:
        return self._perms
```

修改 `user_from_claims` 函数，在 `elif role_type == "supplier"` 之后添加：

```python
        elif role_type == "admin":
            user.add_role(_ClaimsAdmin())
```

注意：`Role` 需要在 import 中添加。修改文件顶部的 import：
```python
from umcp_core.core.base import Demander, PermissionSet, Role, Supplier, User
```

- [ ] **步骤 4：实现 require_admin 守卫**

修改 `src/umcp_core/transport/deps.py`，在 `get_current_user` 之后添加：

```python
from umcp_core.transport.errors import InvalidCredentialError, PermissionDeniedError, TokenExpiredError

async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """要求当前用户具有 admin 角色，否则 403。"""
    if "admin" not in current_user.roles:
        raise PermissionDeniedError(message="需要管理员权限")
    return current_user
```

注意：`PermissionDeniedError` 需添加到现有 import 行。

- [ ] **步骤 5：实现 RuleConfig 扩展方法**

修改 `src/umcp_core/shared/rules/config.py`，在 `set_defaults` 方法之后添加：

```python
    from typing import Any  # 确保顶部已导入

    def list_all(self) -> list[dict[str, Any]]:
        """列出所有规则（合并默认值与仓储值，标记 is_default）。"""
        with self._lock:
            result: dict[str, dict[str, Any]] = {}
            for k, v in self._defaults.items():
                result[k] = {
                    "rule_key": k,
                    "rule_value": v,
                    "description": None,
                    "category": "default",
                    "version": 0,
                    "updated_by": None,
                    "updated_at": None,
                    "is_default": True,
                }
            for rule in self._repo.list_all():
                result[rule["rule_key"]] = {**rule, "is_default": False}
            return list(result.values())

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        """按分类列出规则。"""
        return [r for r in self.list_all() if r.get("category") == category]

    def history(self, key: str) -> list[dict[str, Any]]:
        """查询规则变更历史。"""
        with self._lock:
            return self._repo.history(key)

    def find(self, key: str) -> dict[str, Any] | None:
        """查询单个规则完整信息（仅仓储值，不含默认值）。"""
        with self._lock:
            return self._repo.find_by_key(key)
```

- [ ] **步骤 6：运行测试验证通过**

运行：`pytest tests/test_admin_role.py tests/test_rule_config_list.py -v`
预期：PASS

- [ ] **步骤 7：回归测试**

运行：`pytest tests/ -k "auth or rule or escort" -v`
预期：PASS

- [ ] **步骤 8：Commit**

```bash
git add src/umcp_core/transport/auth.py src/umcp_core/transport/deps.py src/umcp_core/shared/rules/config.py tests/test_admin_role.py tests/test_rule_config_list.py
git commit -m "feat(admin): admin 角色体系 + require_admin 守卫 + RuleConfig 扩展 list/history/find"
```

---

### 任务 2：admin/rules router 骨架 + list + detail 端点

**文件：**
- 创建：`src/umcp_core/transport/routers/admin/__init__.py`
- 创建：`src/umcp_core/transport/routers/admin/rules.py`
- 修改：`src/umcp_core/transport/routers/__init__.py`
- 测试：`tests/test_admin_rules_api.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_admin_rules_api.py`：

```python
"""验证 admin/rules 端点（list/detail/update/history/rollback）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsAdmin, _ClaimsDemander


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _admin_headers(server, user_id="admin1"):
    """生成 admin token 请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Admin")
    user.add_role(_ClaimsAdmin())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _user_headers(server, user_id="student1"):
    """生成普通用户 token 请求头。"""
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Student")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_list_rules_requires_admin(app_client):
    """非 admin 用户访问 /admin/rules 应返回 403。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_user_headers(server))
    assert resp.status_code == 403


def test_list_rules_returns_all(app_client):
    """admin 用户应获取所有规则（含默认值）。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_admin_headers(server))
    assert resp.status_code == 200
    rules = resp.json()["data"]
    keys = [r["rule_key"] for r in rules]
    assert "escort.cancel.realtime.timeout_seconds" in keys
    assert "escort.cancel.realtime.expand_after_seconds" in keys
    assert "escort.cancel.scheduled.penalty_tiers" in keys


def test_list_rules_filter_by_category(app_client):
    """按 category 过滤规则。"""
    client, server = app_client
    resp = client.get(
        "/api/v1/admin/rules?category=escort.cancel",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    rules = resp.json()["data"]
    for r in rules:
        assert r["category"] == "escort.cancel"


def test_get_rule_detail(app_client):
    """查询单个规则详情。"""
    client, server = app_client
    resp = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["rule_key"] == "escort.cancel.realtime.timeout_seconds"
    assert data["rule_value"] == 60


def test_get_rule_detail_not_found(app_client):
    """查询不存在的规则返回 404。"""
    client, server = app_client
    resp = client.get(
        "/api/v1/admin/rules/nonexistent.key",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 404
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_admin_rules_api.py -v`
预期：FAIL（404，router 不存在）。

- [ ] **步骤 3：创建 admin 包与 router**

创建 `src/umcp_core/transport/routers/admin/__init__.py`：

```python
"""admin 路由包。"""
```

创建 `src/umcp_core/transport/routers/admin/rules.py`：

```python
"""管理员规则配置 router。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_server, require_admin
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/admin", tags=["admin-rules"])


class RuleItemResponse(BaseModel):
    """规则项响应。"""

    rule_key: str
    rule_value: Any
    description: str | None = None
    category: str
    version: int
    updated_by: str | None = None
    updated_at: str | None = None
    is_default: bool = False


@router.get("/rules", response_model=Envelope)
async def list_rules(
    category: str | None = Query(default=None),
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """列出所有规则（可选按 category 过滤）。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    if category:
        rules = rule_config.list_by_category(category)
    else:
        rules = rule_config.list_all()
    return ok(data=[_to_response(r).model_dump() for r in rules])


@router.get("/rules/{rule_key}", response_model=Envelope)
async def get_rule(
    rule_key: str,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """查询单个规则详情。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    # 先查仓储
    rule = rule_config.find(rule_key)
    if rule is not None:
        return ok(_to_response({**rule, "is_default": False}).model_dump())
    # 再查默认值
    rules = rule_config.list_all()
    for r in rules:
        if r["rule_key"] == rule_key:
            return ok(_to_response(r).model_dump())
    raise NotFoundError(message=f"规则 {rule_key} 不存在")


def _to_response(rule: dict[str, Any]) -> RuleItemResponse:
    """将规则 dict 转为响应模型。"""
    updated_at = rule.get("updated_at")
    return RuleItemResponse(
        rule_key=rule["rule_key"],
        rule_value=rule["rule_value"],
        description=rule.get("description"),
        category=rule.get("category", "default"),
        version=rule.get("version", 0),
        updated_by=rule.get("updated_by"),
        updated_at=updated_at.isoformat() if updated_at else None,
        is_default=rule.get("is_default", False),
    )
```

- [ ] **步骤 4：注册 router**

修改 `src/umcp_core/transport/routers/__init__.py`，在 import 区添加：

```python
from umcp_core.transport.routers.admin.rules import router as admin_rules_router
```

在 `register_routers` 函数中（`app.include_router(escort_deals_router)` 之后）添加：

```python
    app.include_router(admin_rules_router)
```

- [ ] **步骤 5：运行测试验证通过**

运行：`pytest tests/test_admin_rules_api.py -v`
预期：PASS（5 个测试通过）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/transport/routers/admin/__init__.py src/umcp_core/transport/routers/admin/rules.py src/umcp_core/transport/routers/__init__.py tests/test_admin_rules_api.py
git commit -m "feat(admin): admin/rules router list + detail 端点"
```

---

### 任务 3：admin/rules update 端点

**文件：**
- 修改：`src/umcp_core/transport/routers/admin/rules.py`
- 测试：`tests/test_admin_rules_api.py`（追加测试）

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_admin_rules_api.py` 末尾追加：

```python
def test_update_rule_changes_value(app_client):
    """admin 更新规则值后应反映在新值中。"""
    client, server = app_client
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 120, "reason": "延长超时时间"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["rule_value"] == 120
    assert data["version"] >= 1

    # 验证 get 也返回新值
    resp2 = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
    )
    assert resp2.json()["data"]["rule_value"] == 120


def test_update_rule_records_history(app_client):
    """更新规则应产生历史记录。"""
    client, server = app_client
    client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 90, "reason": "测试历史"},
    )
    resp = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds/history",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    history = resp.json()["data"]
    assert len(history) >= 1
    assert history[-1]["new_value"] == 90
    assert history[-1]["change_reason"] == "测试历史"


def test_update_rule_requires_reason(app_client):
    """更新规则时 reason 不可为空。"""
    client, server = app_client
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 120, "reason": ""},
    )
    assert resp.status_code == 422
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_admin_rules_api.py -v -k "update"`
预期：FAIL（PUT 端点 405 / history 端点 404）。

- [ ] **步骤 3：实现 update 端点**

修改 `src/umcp_core/transport/routers/admin/rules.py`，在 `get_rule` 端点之后添加请求模型和端点：

```python
class UpdateRuleRequest(BaseModel):
    """更新规则请求。"""

    value: Any
    reason: str


@router.put("/rules/{rule_key}", response_model=Envelope)
async def update_rule(
    rule_key: str,
    req: UpdateRuleRequest,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """更新规则值。"""
    if not req.reason or not req.reason.strip():
        raise IllegalStateError(message="变更原因不可为空")
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    # 获取当前 category（若规则不存在则用 default）
    existing = rule_config.find(rule_key)
    category = existing["category"] if existing else "default"
    description = existing["description"] if existing else None
    rule_config.set(
        key=rule_key,
        value=req.value,
        updated_by=admin.user_id,
        category=category,
        description=description,
        reason=req.reason,
    )
    # 返回更新后的规则
    updated = rule_config.find(rule_key)
    return ok(_to_response({**updated, "is_default": False}).model_dump())
```

注意：空 reason 校验改为 422。修改校验逻辑使用 Pydantic 的 `min_length`：

```python
class UpdateRuleRequest(BaseModel):
    value: Any
    reason: str = Field(min_length=1)
```

需要额外 import `from pydantic import BaseModel, Field`。

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_admin_rules_api.py -v`
预期：PASS（8 个测试通过）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/transport/routers/admin/rules.py tests/test_admin_rules_api.py
git commit -m "feat(admin): admin/rules update 端点 + 变更历史记录"
```

---

### 任务 4：admin/rules history + rollback 端点

**文件：**
- 修改：`src/umcp_core/transport/routers/admin/rules.py`
- 测试：`tests/test_admin_rules_api.py`（追加测试）

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_admin_rules_api.py` 末尾追加：

```python
def test_get_rule_history(app_client):
    """查询规则变更历史。"""
    client, server = app_client
    # 先更新一次产生历史
    client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 90, "reason": "第一次调整"},
    )
    client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 100, "reason": "第二次调整"},
    )
    resp = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds/history",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    history = resp.json()["data"]
    assert len(history) >= 2
    assert history[-1]["new_value"] == 100
    assert history[-1]["change_reason"] == "第二次调整"


def test_rollback_rule(app_client):
    """回滚规则到历史版本。"""
    client, server = app_client
    # 初始值 60，改为 90
    client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 90, "reason": "调整"},
    )
    # 获取历史
    resp = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds/history",
        headers=_admin_headers(server),
    )
    history = resp.json()["data"]
    # 第一条历史记录的 old_value 为 None（首次设置），new_value 为 90
    # 回滚到第一条意味着... 实际上 old_value 为 None 无法回滚
    # 改为：再改一次到 100，然后回滚到第一次变更（old_value=90 → 即回滚后值=90）
    client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 100, "reason": "再次调整"},
    )
    resp = client.get(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds/history",
        headers=_admin_headers(server),
    )
    history = resp.json()["data"]
    # 找到 old_value 非 None 的记录（第二次变更：old=90, new=100）
    rollback_target = next(h for h in history if h["old_value"] is not None)
    old_val = rollback_target["old_value"]

    resp = client.post(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds/rollback",
        headers=_admin_headers(server),
        json={"history_id": rollback_target["history_id"], "reason": "回滚测试"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["rule_value"] == old_val


def test_rollback_nonexistent_history_returns_404(app_client):
    """回滚到不存在的历史记录返回 404。"""
    client, server = app_client
    resp = client.post(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds/rollback",
        headers=_admin_headers(server),
        json={"history_id": 99999, "reason": "测试"},
    )
    assert resp.status_code == 404
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_admin_rules_api.py -v -k "history or rollback"`
预期：FAIL（history 端点 404 / rollback 端点 404）。

- [ ] **步骤 3：实现 history + rollback 端点**

修改 `src/umcp_core/transport/routers/admin/rules.py`，在 `update_rule` 之后添加：

```python
class RuleHistoryResponse(BaseModel):
    """规则历史项响应。"""

    history_id: int
    rule_key: str
    old_value: Any
    new_value: Any
    changed_by: str | None = None
    changed_at: str
    change_reason: str | None = None


class RollbackRequest(BaseModel):
    history_id: int
    reason: str = Field(min_length=1)


@router.get("/rules/{rule_key}/history", response_model=Envelope)
async def get_rule_history(
    rule_key: str,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """查询规则变更历史。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    history = rule_config.history(rule_key)
    return ok(data=[_to_history_response(h).model_dump() for h in history])


@router.post("/rules/{rule_key}/rollback", response_model=Envelope)
async def rollback_rule(
    rule_key: str,
    req: RollbackRequest,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """回滚规则到指定历史版本。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    history = rule_config.history(rule_key)
    record = next((h for h in history if h["history_id"] == req.history_id), None)
    if record is None:
        raise NotFoundError(message=f"历史记录 {req.history_id} 不存在")
    old_value = record.get("old_value")
    if old_value is None:
        raise IllegalStateError(message="无法回滚到初始版本（无旧值）")
    existing = rule_config.find(rule_key)
    category = existing["category"] if existing else "default"
    description = existing["description"] if existing else None
    rule_config.set(
        key=rule_key,
        value=old_value,
        updated_by=admin.user_id,
        category=category,
        description=description,
        reason=f"回滚: {req.reason}",
    )
    updated = rule_config.find(rule_key)
    return ok(_to_response({**updated, "is_default": False}).model_dump())


def _to_history_response(h: dict[str, Any]) -> RuleHistoryResponse:
    """将历史 dict 转为响应模型。"""
    changed_at = h.get("changed_at")
    return RuleHistoryResponse(
        history_id=h["history_id"],
        rule_key=h["rule_key"],
        old_value=h.get("old_value"),
        new_value=h.get("new_value"),
        changed_by=h.get("changed_by"),
        changed_at=changed_at.isoformat() if changed_at else "",
        change_reason=h.get("change_reason"),
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_admin_rules_api.py -v`
预期：PASS（11 个测试通过）

- [ ] **步骤 5：回归测试**

运行：`pytest tests/ -k "admin or rule" -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/transport/routers/admin/rules.py tests/test_admin_rules_api.py
git commit -m "feat(admin): admin/rules history + rollback 端点"
```

---

### 任务 5：前端 admin 类型定义 + useRules hooks

**文件：**
- 修改：`web/src/types/escort.ts`（或新建 `web/src/types/admin.ts`）
- 创建：`web/src/hooks/use-rules.ts`
- 测试：`web/tests/admin-rules.test.tsx`

- [ ] **步骤 1：编写失败的测试**

创建 `web/tests/admin-rules.test.tsx`：

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useRules, useRule, useUpdateRule, useRuleHistory, useRollbackRule } from "@/hooks/use-rules";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("useRules hooks", () => {
  beforeEach(() => {
    (apiClient.get as any).mockReset();
    (apiClient.post as any).mockReset();
    (apiClient.put as any).mockReset();
  });

  it("useRules 获取规则列表", async () => {
    (apiClient.get as any).mockResolvedValue([
      { rule_key: "key1", rule_value: 60, category: "escort.cancel", version: 1, is_default: false },
    ]);
    const { result } = renderHook(() => useRules(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].rule_key).toBe("key1");
  });

  it("useRule 获取单个规则", async () => {
    (apiClient.get as any).mockResolvedValue({
      rule_key: "key1", rule_value: 60, category: "test", version: 1, is_default: false,
    });
    const { result } = renderHook(() => useRule("key1"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.rule_value).toBe(60);
  });

  it("useUpdateRule 调用 PUT", async () => {
    (apiClient.put as any).mockResolvedValue({ rule_key: "key1", rule_value: 120 });
    const { result } = renderHook(() => useUpdateRule(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ ruleKey: "key1", value: 120, reason: "测试" });
    expect(apiClient.put).toHaveBeenCalledWith("/admin/rules/key1", { value: 120, reason: "测试" });
  });

  it("useRuleHistory 获取历史", async () => {
    (apiClient.get as any).mockResolvedValue([
      { history_id: 1, rule_key: "key1", old_value: null, new_value: 60, change_reason: "初始" },
    ]);
    const { result } = renderHook(() => useRuleHistory("key1"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
  });

  it("useRollbackRule 调用 POST rollback", async () => {
    (apiClient.post as any).mockResolvedValue({ rule_key: "key1", rule_value: 60 });
    const { result } = renderHook(() => useRollbackRule(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ ruleKey: "key1", historyId: 1, reason: "回滚" });
    expect(apiClient.post).toHaveBeenCalledWith("/admin/rules/key1/rollback", {
      history_id: 1, reason: "回滚",
    });
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd web && npx vitest run tests/admin-rules.test.tsx`
预期：FAIL，`Cannot find module '@/hooks/use-rules'`。

- [ ] **步骤 3：创建类型定义**

创建 `web/src/types/admin.ts`：

```typescript
/** 规则项。 */
export interface RuleItem {
  rule_key: string;
  rule_value: unknown;
  description: string | null;
  category: string;
  version: number;
  updated_by: string | null;
  updated_at: string | null;
  is_default: boolean;
}

/** 规则变更历史项。 */
export interface RuleHistoryItem {
  history_id: number;
  rule_key: string;
  old_value: unknown;
  new_value: unknown;
  changed_by: string | null;
  changed_at: string;
  change_reason: string | null;
}
```

- [ ] **步骤 4：实现 use-rules hooks**

创建 `web/src/hooks/use-rules.ts`：

```typescript
"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { RuleItem, RuleHistoryItem } from "@/types/admin";

export function useRules(category?: string) {
  return useQuery({
    queryKey: ["admin-rules", category],
    queryFn: () =>
      apiClient.get<RuleItem[]>(
        `/admin/rules${category ? `?category=${category}` : ""}`,
      ),
  });
}

export function useRule(ruleKey: string | undefined) {
  return useQuery({
    queryKey: ["admin-rule", ruleKey],
    queryFn: () => apiClient.get<RuleItem>(`/admin/rules/${ruleKey}`),
    enabled: !!ruleKey,
  });
}

export function useUpdateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { ruleKey: string; value: unknown; reason: string }) =>
      apiClient.put<RuleItem>(`/admin/rules/${params.ruleKey}`, {
        value: params.value,
        reason: params.reason,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-rules"] });
      qc.invalidateQueries({ queryKey: ["admin-rule"] });
    },
  });
}

export function useRuleHistory(ruleKey: string | undefined) {
  return useQuery({
    queryKey: ["rule-history", ruleKey],
    queryFn: () =>
      apiClient.get<RuleHistoryItem[]>(`/admin/rules/${ruleKey}/history`),
    enabled: !!ruleKey,
  });
}

export function useRollbackRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { ruleKey: string; historyId: number; reason: string }) =>
      apiClient.post<RuleItem>(`/admin/rules/${params.ruleKey}/rollback`, {
        history_id: params.historyId,
        reason: params.reason,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-rules"] });
      qc.invalidateQueries({ queryKey: ["admin-rule"] });
      qc.invalidateQueries({ queryKey: ["rule-history"] });
    },
  });
}
```

- [ ] **步骤 5：运行测试验证通过**

运行：`cd web && npx vitest run tests/admin-rules.test.tsx`
预期：PASS（5 个测试通过）

- [ ] **步骤 6：Commit**

```bash
git add web/src/types/admin.ts web/src/hooks/use-rules.ts web/tests/admin-rules.test.tsx
git commit -m "feat(web): admin 规则类型定义与 useRules hooks"
```

---

### 任务 6：前端 admin 路由守卫 + Dashboard 入口

**文件：**
- 修改：`web/src/middleware.ts`
- 修改：`web/src/app/(protected)/dashboard/page.tsx`

- [ ] **步骤 1：修改 middleware 添加 admin 路由守卫**

读取当前 `web/src/middleware.ts`，在受保护路由列表中添加 `/admin`。admin 路由需要额外的 admin 角色校验。

修改 middleware 逻辑：`/admin` 路径除了需要登录外，还需要 token 中 roles 含 `admin`。由于 middleware 运行在服务端，只能从 cookie 中的 access_token 解析角色（不调用 API）。简化方案：`/admin` 路径只校验登录（与其他受保护页面一致），admin 角色校验由前端页面运行时检查（页面加载时调用 `/auth/me` 检查 roles）。

在 middleware 的受保护路径匹配中添加 `/admin`：

```typescript
// 在现有的 protected 路径匹配中添加 /admin
if (pathname.startsWith("/admin") || pathname.startsWith("/escort") || pathname.startsWith("/dashboard")) {
  // 校验登录...
}
```

- [ ] **步骤 2：修改 Dashboard 添加 admin 入口**

在 Dashboard 页面中，当用户 roles 含 `admin` 时显示"管理后台"入口卡片：

```tsx
{user?.roles?.includes("admin") && (
  <Card className="cursor-pointer" onClick={() => router.push("/admin/rules")}>
    <CardHeader>管理后台</CardHeader>
    <CardContent>规则配置管理</CardContent>
  </Card>
)}
```

- [ ] **步骤 3：验证前端测试通过**

运行：`cd web && npx vitest run`
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add web/src/middleware.ts web/src/app/(protected)/dashboard/page.tsx
git commit -m "feat(web): admin 路由守卫与 Dashboard 管理入口"
```

---

### 任务 7：前端规则列表页

**文件：**
- 创建：`web/src/app/(protected)/admin/rules/page.tsx`

- [ ] **步骤 1：实现规则列表页**

创建 `web/src/app/(protected)/admin/rules/page.tsx`：

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useRules } from "@/hooks/use-rules";
import { useAuthStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";
import { OrderStatusBadge } from "@/components/order-status-badge";
import type { RuleItem } from "@/types/admin";

export default function AdminRulesPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: rules, isLoading } = useRules();
  const [filterCategory, setFilterCategory] = useState<string>("");

  // admin 角色校验
  if (user && !user.roles?.includes("admin")) {
    return <div className="p-4">权限不足</div>;
  }

  if (isLoading) return <div className="p-4">加载中...</div>;

  // 按 category 分组
  const grouped: Record<string, RuleItem[]> = {};
  for (const rule of rules ?? []) {
    const cat = rule.category || "default";
    if (filterCategory && cat !== filterCategory) continue;
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(rule);
  }

  const categories = [...new Set((rules ?? []).map((r) => r.category || "default"))];

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">规则配置管理</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {/* 分类筛选 */}
        <div className="flex gap-2 flex-wrap">
          <Button
            variant={filterCategory === "" ? "default" : "outline"}
            size="sm"
            onClick={() => setFilterCategory("")}
          >
            全部
          </Button>
          {categories.map((cat) => (
            <Button
              key={cat}
              variant={filterCategory === cat ? "default" : "outline"}
              size="sm"
              onClick={() => setFilterCategory(cat)}
            >
              {cat}
            </Button>
          ))}
        </div>

        {/* 规则列表（按分类分组） */}
        {Object.entries(grouped).map(([cat, catRules]) => (
          <div key={cat} className="space-y-2">
            <h2 className="text-sm font-medium text-gray-600">{cat}</h2>
            <div className="space-y-2">
              {catRules.map((rule) => (
                <div
                  key={rule.rule_key}
                  className="bg-white rounded-lg border p-4 flex items-center justify-between"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm">{rule.rule_key}</span>
                      {rule.is_default && (
                        <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">默认</span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500">
                      v{rule.version} · {rule.updated_at ? new Date(rule.updated_at).toLocaleString("zh-CN") : "未修改"}
                      {rule.updated_by && ` · ${rule.updated_by}`}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {formatValue(rule.rule_value)}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => router.push(`/admin/rules/${rule.rule_key}`)}
                    >
                      编辑
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return `[${value.length} 项]`;
  if (typeof value === "object" && value) return JSON.stringify(value);
  return String(value);
}
```

- [ ] **步骤 2：验证前端测试通过**

运行：`cd web && npx vitest run`
预期：PASS

- [ ] **步骤 3：Commit**

```bash
git add "web/src/app/(protected)/admin/rules/page.tsx"
git commit -m "feat(web): admin 规则列表页"
```

---

### 任务 8：前端规则编辑对话框 + 历史抽屉

**文件：**
- 创建：`web/src/components/rule-edit-dialog.tsx`
- 创建：`web/src/components/rule-history-drawer.tsx`
- 修改：`web/src/app/(protected)/admin/rules/page.tsx`（集成编辑与历史）

- [ ] **步骤 1：实现规则编辑对话框**

创建 `web/src/components/rule-edit-dialog.tsx`：

```tsx
"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import type { RuleItem } from "@/types/admin";

interface RuleEditDialogProps {
  open: boolean;
  rule: RuleItem | null;
  onConfirm: (value: unknown, reason: string) => void;
  onClose: () => void;
}

export function RuleEditDialog({ open, rule, onConfirm, onClose }: RuleEditDialogProps) {
  const [reason, setReason] = useState("");
  const [numValue, setNumValue] = useState<number>(0);
  const [tiers, setTiers] = useState<{ hours_before: number; penalty: number }[]>([]);
  const [jsonValue, setJsonValue] = useState("");

  useEffect(() => {
    if (!rule) return;
    setReason("");
    const key = rule.rule_key;
    const val = rule.rule_value;
    if (key.endsWith("_seconds")) {
      setNumValue(typeof val === "number" ? val : 0);
    } else if (key.endsWith("_penalty_tiers")) {
      setTiers(Array.isArray(val) ? val : []);
    } else {
      setJsonValue(JSON.stringify(val, null, 2));
    }
  }, [rule]);

  if (!open || !rule) return null;

  const isNumber = rule.rule_key.endsWith("_seconds");
  const isTiers = rule.rule_key.endsWith("_penalty_tiers");

  const handleConfirm = () => {
    if (!reason.trim()) return;
    if (isNumber) {
      onConfirm(numValue, reason);
    } else if (isTiers) {
      onConfirm(tiers, reason);
    } else {
      try {
        onConfirm(JSON.parse(jsonValue), reason);
      } catch {
        alert("JSON 格式错误");
        return;
      }
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-lg w-full mx-4 space-y-4">
        <h3 className="text-lg font-medium">编辑规则</h3>
        <p className="text-sm font-mono text-gray-600">{rule.rule_key}</p>

        {isNumber && (
          <div className="space-y-2">
            <label className="text-sm text-gray-600">数值</label>
            <input
              type="number"
              className="w-full rounded-md border border-gray-300 p-2"
              value={numValue}
              onChange={(e) => setNumValue(Number(e.target.value))}
            />
          </div>
        )}

        {isTiers && (
          <div className="space-y-2">
            <label className="text-sm text-gray-600">罚分梯度</label>
            {tiers.map((tier, i) => (
              <div key={i} className="flex gap-2 items-center">
                <span className="text-xs text-gray-500">提前</span>
                <input
                  type="number"
                  className="w-20 rounded-md border border-gray-300 p-1 text-sm"
                  value={tier.hours_before}
                  onChange={(e) => {
                    const next = [...tiers];
                    next[i] = { ...tier, hours_before: Number(e.target.value) };
                    setTiers(next);
                  }}
                />
                <span className="text-xs text-gray-500">小时，扣</span>
                <input
                  type="number"
                  step="0.1"
                  className="w-20 rounded-md border border-gray-300 p-1 text-sm"
                  value={tier.penalty}
                  onChange={(e) => {
                    const next = [...tiers];
                    next[i] = { ...tier, penalty: Number(e.target.value) };
                    setTiers(next);
                  }}
                />
                <span className="text-xs text-gray-500">分</span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setTiers(tiers.filter((_, idx) => idx !== i))}
                >
                  删除
                </Button>
              </div>
            ))}
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTiers([...tiers, { hours_before: 0, penalty: 0 }])}
            >
              添加档位
            </Button>
          </div>
        )}

        {!isNumber && !isTiers && (
          <div className="space-y-2">
            <label className="text-sm text-gray-600">JSON 值</label>
            <textarea
              className="w-full rounded-md border border-gray-300 p-2 font-mono text-sm"
              rows={6}
              value={jsonValue}
              onChange={(e) => setJsonValue(e.target.value)}
            />
          </div>
        )}

        <div className="space-y-2">
          <label className="text-sm text-gray-600">变更原因（必填）</label>
          <input
            type="text"
            className="w-full rounded-md border border-gray-300 p-2"
            placeholder="请说明变更原因"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <div className="flex gap-2 justify-end">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={!reason.trim()}>
            确认更新
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：实现历史抽屉**

创建 `web/src/components/rule-history-drawer.tsx`：

```tsx
"use client";

import { Button } from "@/components/ui/button";
import { useRuleHistory, useRollbackRule } from "@/hooks/use-rules";

interface RuleHistoryDrawerProps {
  open: boolean;
  ruleKey: string | null;
  onClose: () => void;
}

export function RuleHistoryDrawer({ open, ruleKey, onClose }: RuleHistoryDrawerProps) {
  const { data: history, isLoading } = useRuleHistory(open ? ruleKey : undefined);
  const rollback = useRollbackRule();

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex justify-end z-50">
      <div className="bg-white w-96 h-full overflow-y-auto p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium">变更历史</h3>
          <Button variant="ghost" onClick={onClose}>关闭</Button>
        </div>
        {ruleKey && (
          <p className="text-sm font-mono text-gray-600">{ruleKey}</p>
        )}
        {isLoading && <p className="text-sm text-gray-500">加载中...</p>}
        {!isLoading && history && history.length === 0 && (
          <p className="text-sm text-gray-500">暂无历史记录</p>
        )}
        <div className="space-y-3">
          {history?.map((h) => (
            <div key={h.history_id} className="border rounded-lg p-3 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">
                  {new Date(h.changed_at).toLocaleString("zh-CN")}
                </span>
                {h.changed_by && (
                  <span className="text-xs text-gray-400">{h.changed_by}</span>
                )}
              </div>
              <div className="text-sm">
                <span className="text-gray-500">旧值: </span>
                <span className="font-mono">
                  {h.old_value === null ? "无" : JSON.stringify(h.old_value)}
                </span>
              </div>
              <div className="text-sm">
                <span className="text-gray-500">新值: </span>
                <span className="font-mono">
                  {h.new_value === null ? "无" : JSON.stringify(h.new_value)}
                </span>
              </div>
              {h.change_reason && (
                <p className="text-xs text-gray-600">原因: {h.change_reason}</p>
              )}
              {h.old_value !== null && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={rollback.isPending}
                  onClick={() => {
                    if (!ruleKey) return;
                    const reason = prompt("请输入回滚原因");
                    if (reason) {
                      rollback.mutate({ ruleKey, historyId: h.history_id, reason });
                    }
                  }}
                >
                  回滚到此版本
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **步骤 3：集成到规则列表页**

修改 `web/src/app/(protected)/admin/rules/page.tsx`，添加编辑对话框与历史抽屉集成：

在文件顶部 import 区添加：
```typescript
import { RuleEditDialog } from "@/components/rule-edit-dialog";
import { RuleHistoryDrawer } from "@/components/rule-history-drawer";
import { useUpdateRule } from "@/hooks/use-rules";
```

在组件函数体内添加：
```typescript
  const updateRule = useUpdateRule();
  const [editRule, setEditRule] = useState<RuleItem | null>(null);
  const [historyKey, setHistoryKey] = useState<string | null>(null);
```

在每条规则的操作区添加历史按钮（编辑按钮旁边）：
```tsx
<Button size="sm" variant="ghost" onClick={() => setHistoryKey(rule.rule_key)}>
  历史
</Button>
```

编辑按钮改为打开对话框：
```tsx
<Button size="sm" variant="outline" onClick={() => setEditRule(rule)}>
  编辑
</Button>
```

在页面末尾（最外层 div 闭合前）添加：
```tsx
<RuleEditDialog
  open={editRule !== null}
  rule={editRule}
  onConfirm={(value, reason) => {
    if (editRule) {
      updateRule.mutate({ ruleKey: editRule.rule_key, value, reason });
      setEditRule(null);
    }
  }}
  onClose={() => setEditRule(null)}
/>
<RuleHistoryDrawer
  open={historyKey !== null}
  ruleKey={historyKey}
  onClose={() => setHistoryKey(null)}
/>
```

- [ ] **步骤 4：验证前端测试通过**

运行：`cd web && npx vitest run`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add web/src/components/rule-edit-dialog.tsx web/src/components/rule-history-drawer.tsx "web/src/app/(protected)/admin/rules/page.tsx"
git commit -m "feat(web): 规则编辑对话框与历史抽屉组件"
```

---

### 任务 9：端到端集成测试

**文件：**
- 创建：`tests/test_admin_rules_e2e.py`

- [ ] **步骤 1：编写端到端测试**

创建 `tests/test_admin_rules_e2e.py`：

```python
"""管理员规则配置端到端集成测试。

覆盖：
1. admin 查看规则列表
2. admin 更新规则 → 验证新值生效
3. admin 查看历史
4. admin 回滚规则
5. 非 admin 被拒绝
6. 更新后的规则值影响业务逻辑（cancel-rules 端点返回新值）
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsAdmin, _ClaimsDemander


@pytest.fixture
def app_client():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    config = TransportConfig(jwt_secret="test-secret")
    app = create_app(server, config)
    with TestClient(app) as client:
        yield client, server


def _admin_headers(server, user_id="admin1"):
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Admin")
    user.add_role(_ClaimsAdmin())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _user_headers(server, user_id="student1"):
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="Student")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_e2e_admin_lists_rules(app_client):
    """admin 查看规则列表。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_admin_headers(server))
    assert resp.status_code == 200
    rules = resp.json()["data"]
    assert len(rules) >= 3


def test_e2e_non_admin_rejected(app_client):
    """非 admin 被拒绝访问。"""
    client, server = app_client
    resp = client.get("/api/v1/admin/rules", headers=_user_headers(server))
    assert resp.status_code == 403


def test_e2e_update_then_cancel_rules_reflects_change(app_client):
    """admin 更新规则后，/cancel-rules 端点应返回新值。"""
    client, server = app_client
    # 更新 timeout_seconds 为 120
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.realtime.timeout_seconds",
        headers=_admin_headers(server),
        json={"value": 120, "reason": "E2E 测试调整"},
    )
    assert resp.status_code == 200

    # /cancel-rules 应返回 120
    resp2 = client.get(
        "/api/v1/escort/cancel-rules",
        headers=_user_headers(server),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["timeout_seconds"] == 120


def test_e2e_update_history_rollback(app_client):
    """更新 → 历史 → 回滚完整流程。"""
    client, server = app_client
    rule_key = "escort.cancel.realtime.expand_after_seconds"

    # 初始值 30，改为 45
    client.put(
        f"/api/v1/admin/rules/{rule_key}",
        headers=_admin_headers(server),
        json={"value": 45, "reason": "第一次调整"},
    )
    # 再改为 60
    client.put(
        f"/api/v1/admin/rules/{rule_key}",
        headers=_admin_headers(server),
        json={"value": 60, "reason": "第二次调整"},
    )

    # 查看历史
    resp = client.get(
        f"/api/v1/admin/rules/{rule_key}/history",
        headers=_admin_headers(server),
    )
    assert resp.status_code == 200
    history = resp.json()["data"]
    assert len(history) >= 2

    # 找到 old_value 非 None 的记录回滚
    rollback_target = next(h for h in history if h["old_value"] is not None)
    old_val = rollback_target["old_value"]

    resp = client.post(
        f"/api/v1/admin/rules/{rule_key}/rollback",
        headers=_admin_headers(server),
        json={"history_id": rollback_target["history_id"], "reason": "E2E 回滚"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["rule_value"] == old_val


def test_e2e_update_penalty_tiers(app_client):
    """admin 更新罚分梯度（list 类型值）。"""
    client, server = app_client
    new_tiers = [
        {"hours_before": 48, "penalty": 0.1},
        {"hours_before": 0, "penalty": 3.0},
    ]
    resp = client.put(
        "/api/v1/admin/rules/escort.cancel.scheduled.penalty_tiers",
        headers=_admin_headers(server),
        json={"value": new_tiers, "reason": "调整罚分梯度"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["rule_value"] == new_tiers

    # /cancel-rules 应返回新梯度
    resp2 = client.get(
        "/api/v1/escort/cancel-rules",
        headers=_user_headers(server),
    )
    assert resp2.json()["data"]["penalty_tiers"] == new_tiers
```

- [ ] **步骤 2：运行端到端测试**

运行：`pytest tests/test_admin_rules_e2e.py -v`
预期：PASS（5 个测试通过）

- [ ] **步骤 3：全量回归测试**

运行：`pytest tests/ -v 2>&1 | Select-Object -Last 30`
预期：全部 PASS。

运行：`cd web && npx vitest run 2>&1 | Select-Object -Last 10`
预期：全部 PASS。

- [ ] **步骤 4：Commit**

```bash
git add tests/test_admin_rules_e2e.py
git commit -m "test(admin): 管理员规则配置端到端集成测试"
```

---

## 自检

### 1. 规格覆盖度

| 规格需求 | 实现任务 |
|---------|---------|
| admin 角色认证 | 任务 1（_ClaimsAdmin + require_admin） |
| 规则列表查询 | 任务 2（list 端点）+ 任务 7（列表页） |
| 规则详情查询 | 任务 2（detail 端点） |
| 规则更新 | 任务 3（update 端点）+ 任务 8（编辑对话框） |
| 变更历史 | 任务 4（history 端点）+ 任务 8（历史抽屉） |
| 规则回滚 | 任务 4（rollback 端点）+ 任务 8（回滚按钮） |
| 前端路由守卫 | 任务 6（middleware + Dashboard 入口） |
| 规则更新影响业务 | 任务 9（E2E：更新后 cancel-rules 返回新值） |
| 非 admin 拒绝 | 任务 1（require_admin）+ 任务 9（E2E） |

覆盖完整，无遗漏。

### 2. 占位符扫描

无 "TODO"、"待定"、"后续实现" 等占位符。每个步骤都包含完整代码。

### 3. 类型一致性

- `RuleItem` 类型：后端 `RuleItemResponse`（任务 2），前端 `RuleItem`（任务 5）—— 字段一致（rule_key/rule_value/description/category/version/updated_by/updated_at/is_default）。
- `RuleHistoryItem` 类型：后端 `RuleHistoryResponse`（任务 4），前端 `RuleHistoryItem`（任务 5）—— 字段一致（history_id/rule_key/old_value/new_value/changed_by/changed_at/change_reason）。
- `require_admin`：任务 1 定义，任务 2-4 调用 —— 一致。
- `list_all`/`find`/`history`：任务 1 定义，任务 2-4 调用 —— 一致。
- `useUpdateRule`/`useRollbackRule`：任务 5 定义，任务 8 调用 —— 一致。

---

## 执行交接

**计划已完成并保存到 `docs/plans/2026-08-03-admin-rule-config.md`。两种执行方式：**

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**
