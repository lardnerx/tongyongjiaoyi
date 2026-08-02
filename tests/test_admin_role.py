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
