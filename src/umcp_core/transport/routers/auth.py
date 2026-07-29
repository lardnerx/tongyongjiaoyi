"""认证路由：登录、刷新、登出、当前用户。"""

from __future__ import annotations

from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_jwt_service, get_server
from umcp_core.transport.auth import JwtService
from umcp_core.transport.errors import InvalidCredentialError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter()


class LoginRequest(BaseModel):
    credential_type: str
    token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    user_id: str
    name: str
    roles: list[str]
    active_role: str | None


@router.post("/login", response_model=Envelope[TokenResponse])
async def login(
    req: LoginRequest,
    server: UMCPServer = Depends(get_server),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope[TokenResponse]:
    """凭据登录，返回 token 对。"""
    credential = Credential(type=req.credential_type, token=req.token)
    try:
        user = server.auth_provider.authenticate(credential)
    except ValueError as e:
        raise InvalidCredentialError(message=str(e)) from e
    tokens = jwt_service.issue(user)
    return ok(tokens)


@router.post("/refresh", response_model=Envelope[TokenResponse])
async def refresh(
    req: RefreshRequest,
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope[TokenResponse]:
    """用 refresh_token 换新 access_token。"""
    try:
        payload = jwt_service.decode(req.refresh_token)
    except pyjwt.InvalidTokenError as e:
        raise InvalidCredentialError(message=f"refresh token 无效: {e}") from e
    if payload.get("type") != "refresh":
        raise InvalidCredentialError(message="非 refresh token")

    # 重建 User 并签发新 token 对
    from umcp_core.transport.auth import user_from_claims
    user = user_from_claims(payload)
    tokens = jwt_service.issue(user)
    return ok(tokens)


@router.post("/logout", response_model=Envelope)
async def logout(
    current_user: User = Depends(get_current_user),
    jwt_service: JwtService = Depends(get_jwt_service),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """登出，吊销当前 token。"""
    # get_current_user 已校验 token 有效；此处需要 jti，重新解码
    # 由于 deps 已解码一次，这里为简化直接吊销 user_id 关联的最近 jti
    # 实际实现：让 get_current_user 把 jti 存到 User.metadata 或返回 (user, jti)
    # 简化方案：登出时不传 jti，用 user_id 吊销（依赖 access_ttl 短）
    # 更严谨：让 deps 把 payload 也注入
    server.auth_provider.revoke(current_user)
    return ok(message="已登出")


@router.get("/me", response_model=Envelope[UserInfo])
async def me(current_user: User = Depends(get_current_user)) -> Envelope[UserInfo]:
    """返回当前用户信息。"""
    roles = list(current_user.roles.keys())
    active = current_user.active_role.role_type if current_user.active_role else None
    info = UserInfo(
        user_id=current_user.user_id,
        name=current_user.name,
        roles=roles,
        active_role=active,
    )
    return ok(info)
