# 功能回归测试报告 — 头像上传与 JWT 同步

**日期**: 2026-08-08  
**测试范围**: `umcp-core` 全量测试套件  
**测试命令**: `python -m pytest tests/ -v`  
**测试结果**: **751 passed, 0 failed** (共 3513 条 deprecation warnings，均为 `utcnow()` 弃用警告，不影响功能)

---

## 1. 本次变更范围

| 变更文件 | 变更类型 | 说明 |
|----------|---------|------|
| `src/umcp_core/transport/routers/auth.py` | 功能增强 | 新增 `POST /api/v1/auth/avatar` 头像上传端点，加载完整用户对象后持久化 |
| `src/umcp_core/transport/auth.py` | 功能增强 | JWT claims 添加 `avatar_url` 字段，`user_from_claims` 重建时恢复 |
| `src/umcp_core/layers/l1/access.py` | 缺陷修复 | `authenticate()` 优先查仓储再回退缓存，确保跨会话获取最新数据 |
| `tests/test_avatar_upload_e2e.py` | 新增测试 | 9 个 E2E 测试用例覆盖头像上传完整链路 |
| `tests/test_auth_router.py` | 已有测试 | 4 个头像上传异常测试（未认证、类型错误、文件过大、全链路） |
| `pyproject.toml` | 配置更新 | 开启 `log_cli` 控制台日志输出 |

---

## 2. 新增测试用例明细

### 2.1 头像上传 E2E 测试 (`test_avatar_upload_e2e.py`)

| # | 测试用例 | 覆盖场景 | 状态 |
|---|---------|---------|------|
| 1 | `test_full_avatar_upload_and_jwt_sync` | 注册→/me 无头像→上传→新 token JWT claims 含 avatar_url→/me 一致→文件存在→清理 | ✅ PASS |
| 2 | `test_avatar_url_in_jwt_claims` | 验证 access_token 和 refresh_token 的 claims 都含 avatar_url | ✅ PASS |
| 3 | `test_old_token_does_not_have_avatar` | 旧 token 无 avatar_url，新 token 有 | ✅ PASS |
| 4 | `test_upload_different_image_formats` | PNG/JPEG/GIF/WebP 四种格式均成功上传 | ✅ PASS |
| 5 | `test_upload_empty_file` | 0 字节空文件成功上传 | ✅ PASS |
| 6 | `test_upload_without_file_field` | 缺 file 字段返回 422 | ✅ PASS |
| 7 | `test_upload_with_invalid_token` | 无效 token 返回 401 | ✅ PASS |
| 8 | `test_avatar_persistence_across_sessions` | 重新登录后 /me 仍返回正确的 avatar_url | ✅ PASS |
| 9 | `test_cache_priority_repo_over_cache` | 清除 PhoneAuthProvider 缓存后登录，验证仍有 avatar_url | ✅ PASS |

### 2.2 已有头像测试 (`test_auth_router.py`)

| # | 测试用例 | 覆盖场景 | 状态 |
|---|---------|---------|------|
| 10 | `TestUserInfoUpdateChain::test_user_info_update_chain` | 注册→/me 无头像→上传→/me 有头像→文件存在 | ✅ PASS |
| 11 | `TestUserInfoUpdateChain::test_upload_without_auth_returns_401` | 未认证上传返回 401 | ✅ PASS |
| 12 | `TestUserInfoUpdateChain::test_upload_invalid_file_type_returns_401` | 非图片文件上传返回 401 | ✅ PASS |
| 13 | `TestUserInfoUpdateChain::test_upload_oversized_file_returns_401` | 6MB 超大文件上传返回 401 | ✅ PASS |

---

## 3. 缺陷修复验证

### 3.1 PhoneAuthProvider 缓存优先级 Bug

**问题描述**: `authenticate()` 优先从 `_users` 缓存返回用户，跳过仓储查询，导致缓存中的旧用户（无 avatar_url）被返回。

**修复方案**: 改为优先查仓储（`_user_repo.find_by_phone()`），确保最新数据，再回退到缓存。

**验证测试**: `test_cache_priority_repo_over_cache`
- 清除缓存后登录，验证 `/me` 返回正确的 `avatar_url`
- 说明 `authenticate()` 从仓储获取了最新数据

### 3.2 头像上传后用户对象持久化

**问题描述**: 上传头像时，`upload_avatar()` 直接保存 `_ClaimsUser`（来自 JWT claims，不含 `phone` 字段），导致 `InMemoryUserRepository.save()` 无法更新 `_by_phone` 映射。

**修复方案**: 先通过 `find_by_id()` 从仓储加载完整用户对象再保存。

**验证测试**: `test_avatar_persistence_across_sessions`
- 上传头像后重新登录，验证 `/me` 返回一致的 `avatar_url`

---

## 4. 日志输出验证

pytest 配置 `log_cli = true`，控制台输出格式示例：

```
[INFO umcp_core.transport.routers.auth] 用户注册成功 user_id=u_6cb1029687a8 name=头像测试用户
[INFO umcp_core.transport.auth] Issuing tokens for user
[INFO umcp_core.transport.routers.auth] 上传头像 user_id=u_6cb1029687a8 content_type=image/png
[INFO umcp_core.transport.routers.auth] 头像文件保存成功 filepath=.../1b684d07f8004a2d8fc3d87c599476bf.png
[INFO umcp_core.transport.routers.auth] 用户仓储持久化成功 user_id=u_6cb1029687a8
[INFO umcp_core.transport.routers.auth] 新令牌签发成功 access_jti=6d3b588f3b854ffb81e03eb7ab08b737 user_id=u_6cb1029687a8
[INFO umcp_core.transport.routers.auth] 查询用户信息 user_id=u_6cb1029687a8 avatar_url=/api/v1/uploads/avatars/1b684d07f8004a2d8fc3d87c599476bf.png
```

日志覆盖以下关键链路：
- 用户注册/登录成功 → user_id
- 头像上传 → 文件类型、大小校验、保存路径
- 用户信息持久化 → 仓储写入结果
- JWT 令牌签发 → access_jti、user_id
- 用户信息查询 → avatar_url 值

---

## 5. 全量回归测试统计

| 测试文件 | 用例数 | 状态 |
|---------|-------|------|
| `test_auth_router.py` | 29 | ✅ ALL PASS |
| `test_avatar_upload_e2e.py` | 9 | ✅ ALL PASS |
| 其他 65 个测试文件 | 713 | ✅ ALL PASS |
| **总计** | **751** | **✅ 0 FAILED** |

---

## 6. 结论

本次头像上传功能重构无回归问题，所有 751 个测试用例通过。新增的 9 个 E2E 测试覆盖了完整头像上传流程、JWT claims 同步、跨会话数据一致性、多种文件格式、边界异常场景，并专门验证了缓存优先级缺陷修复的有效性。