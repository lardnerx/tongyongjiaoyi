"""FastAPI 依赖注入：JWT 校验、User 重建、server 注入。"""

from __future__ import annotations

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from umcp_core.core.base import User
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService, user_from_claims
from umcp_core.transport.errors import InvalidCredentialError, TokenExpiredError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=True)


def get_server(request: Request) -> UMCPServer:
    """从 app.state 获取 UMCPServer 单例。"""
    return request.app.state.server


def get_jwt_service(request: Request) -> JwtService:
    """从 app.state 获取 JwtService 单例。"""
    return request.app.state.jwt_service


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> User:
    """校验 JWT 并重建 User。失败抛 401。"""
    try:
        payload = jwt_service.decode(token)
    except pyjwt.ExpiredSignatureError as e:
        raise TokenExpiredError() from e
    except pyjwt.InvalidTokenError as e:
        raise InvalidCredentialError(message=f"无效 token: {e}") from e

    if jwt_service.is_revoked(payload.get("jti", "")):
        raise InvalidCredentialError(message="token 已吊销")

    return user_from_claims(payload)
