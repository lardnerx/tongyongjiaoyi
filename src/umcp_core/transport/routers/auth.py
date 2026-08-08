"""认证路由：登录、刷新、登出、当前用户、头像上传。"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends, Request, UploadFile, File
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_jwt_service, get_server
from umcp_core.transport.auth import JwtService, user_from_claims
from umcp_core.transport.errors import IllegalStateError, InvalidCredentialError
from umcp_core.transport.schemas import Envelope, ok

logger = logging.getLogger(__name__)

# 头像存储目录
AVATAR_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "uploads" / "avatars"

router = APIRouter()


def _ensure_avatar_dir() -> Path:
    """确保头像存储目录存在并返回。"""
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    return AVATAR_DIR


class LoginRequest(BaseModel):
    credential_type: str
    token: str
    password: str = ""


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RegisterRequest(BaseModel):
    phone: str
    name: str
    password: str = ""


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    user_id: str
    name: str
    roles: list[str]
    active_role: str | None
    avatar_url: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    phone: str
    new_password: str


@router.post("/login", response_model=Envelope[TokenResponse])
async def login(
    req: LoginRequest,
    server: UMCPServer = Depends(get_server),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope[TokenResponse]:
    """凭据登录，返回 token 对。支持可选密码验证。"""
    credential = Credential(type=req.credential_type, token=req.token)
    if req.password:
        credential.payload["password"] = req.password
    try:
        user = server.auth_provider.authenticate(credential)
        logger.info("用户登录成功 user_id=%s", user.user_id)
    except ValueError as e:
        raise InvalidCredentialError(message=str(e)) from e
    tokens = jwt_service.issue(user)
    return ok(tokens)


@router.post("/register", response_model=Envelope[TokenResponse])
async def register(
    req: RegisterRequest,
    server: UMCPServer = Depends(get_server),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope[TokenResponse]:
    """手机号注册，返回 token 对（自动登录）。支持可选密码。"""
    credential = Credential(type="phone", token=req.phone)
    if req.password:
        credential.payload["password"] = req.password
    try:
        user = server.auth_provider.register(credential, name=req.name)
        logger.info("用户注册成功 user_id=%s name=%s", user.user_id, user.name)
    except ValueError as e:
        raise InvalidCredentialError(message=str(e)) from e
    tokens = jwt_service.issue(user)
    return ok(tokens)


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


@router.post("/logout", response_model=Envelope)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    jwt_service: JwtService = Depends(get_jwt_service),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """登出，吊销当前 access token 及其关联的 refresh token。"""
    # 从 Authorization header 提取 token 并解码获取 jti
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


@router.get("/me", response_model=Envelope[UserInfo])
async def me(current_user: User = Depends(get_current_user)) -> Envelope[UserInfo]:
    """返回当前用户信息。"""
    roles = list(current_user.roles.keys())
    active = current_user.active_role.role_type if current_user.active_role else None
    avatar_url = current_user.metadata.get("avatar_url") if current_user.metadata else None
    logger.info("查询用户信息 user_id=%s avatar_url=%s", current_user.user_id, avatar_url)
    info = UserInfo(
        user_id=current_user.user_id,
        name=current_user.name,
        roles=roles,
        active_role=active,
        avatar_url=avatar_url,
    )
    return ok(info)


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
        raise IllegalStateError(message=str(e)) from e
    tokens = jwt_service.issue(current_user)
    return ok(tokens)


@router.post("/change-password", response_model=Envelope)
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    server: UMCPServer = Depends(get_server),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope:
    """修改当前用户密码。"""
    try:
        updated_user = server.auth_provider.change_password(
            current_user.user_id, req.old_password, req.new_password
        )
    except ValueError as e:
        raise InvalidCredentialError(message=str(e)) from e
    return ok(message="密码修改成功，下次登录时生效")


@router.post("/reset-password", response_model=Envelope)
async def reset_password(
    req: ResetPasswordRequest,
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """重置密码（无需旧密码，用于忘记密码场景）。"""
    try:
        server.auth_provider.reset_password(req.phone, req.new_password)
    except ValueError as e:
        raise InvalidCredentialError(message=str(e)) from e
    return ok(message="密码重置成功，请使用新密码登录")


@router.post("/avatar", response_model=Envelope[dict])
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    server: UMCPServer = Depends(get_server),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Envelope[dict]:
    """上传当前用户头像（仅支持图片格式，最大 5MB）。"""
    # 验证文件类型
    content_type = file.content_type or ""
    logger.info("上传头像 user_id=%s content_type=%s", current_user.user_id, content_type)
    if not content_type.startswith("image/"):
        logger.info("头像文件类型校验失败 content_type=%s", content_type)
        raise InvalidCredentialError(message="仅支持图片文件")

    # 读取文件内容
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        logger.info("头像文件大小超限 user_id=%s file_size=%d", current_user.user_id, len(raw))
        raise InvalidCredentialError(message="头像文件大小不能超过 5MB")

    # 生成唯一文件名
    ext = Path(file.filename or "avatar.png").suffix or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    avatar_dir = _ensure_avatar_dir()
    filepath = avatar_dir / filename

    # 保存文件
    with open(filepath, "wb") as f:
        f.write(raw)
    logger.info("头像文件保存成功 filepath=%s filename=%s", str(filepath), filename)

    # 构建头像 URL
    avatar_url = f"/api/v1/uploads/avatars/{filename}"

    # 从仓储加载完整用户对象（包含 phone 等字段），确保 _by_phone 映射同步更新
    if server.user_repo:
        db_user = server.user_repo.find_by_id(current_user.user_id)
        if db_user is not None:
            if db_user.metadata is None:
                db_user.metadata = {}
            db_user.metadata["avatar_url"] = avatar_url
            server.user_repo.save(db_user)
            logger.info("用户仓储持久化成功 user_id=%s", current_user.user_id)
            current_user = db_user
        else:
            # 兜底：直接使用 current_user
            if current_user.metadata is None:
                current_user.metadata = {}
            current_user.metadata["avatar_url"] = avatar_url
            server.user_repo.save(current_user)
            logger.info("用户仓储持久化成功（兜底）user_id=%s", current_user.user_id)
    else:
        logger.info("用户仓储不可用，跳过持久化 user_id=%s", current_user.user_id)

    # 签发新 token（携带更新后的用户信息）
    tokens = jwt_service.issue(current_user)
    try:
        access_payload = jwt_service.decode(tokens["access_token"])
        logger.info("新令牌签发成功 access_jti=%s user_id=%s", access_payload.get("jti"), current_user.user_id)
    except Exception:
        logger.info("新令牌签发成功（解码 jti 失败）user_id=%s", current_user.user_id)
    return ok({
        "avatar_url": avatar_url,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens["token_type"],
        "expires_in": tokens["expires_in"],
    })
