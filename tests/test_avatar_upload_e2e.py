"""头像上传与 JWT 同步 E2E 测试。

覆盖场景：完整上传流程、JWT claims 验证、token 新旧对比、多种图片格式、
空文件上传、缺少文件字段、无效 token、跨会话持久化。
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService
from umcp_core.transport.errors import register_exception_handlers
from umcp_core.transport.routers.auth import router


# =============================================================================
# 辅助函数
# =============================================================================


def _make_app() -> FastAPI:
    """创建带内存仓储 + PhoneAuthProvider + JwtService 的 FastAPI 测试应用。"""
    server = UMCPServer()
    server.set_auth_provider(PhoneAuthProvider())
    server.use_in_memory_repositories()
    jwt_service = JwtService(secret="test-secret")

    app = FastAPI()
    app.state.server = server
    app.state.jwt_service = jwt_service
    app.include_router(router, prefix="/api/v1/auth")
    register_exception_handlers(app)
    return app


def _make_test_image() -> bytes:
    """生成一个 1x1 像素的 PNG 测试图片字节。"""
    width, height = 1, 1
    raw = b"\x00" + b"\xff\x00\x00\xff"  # filter byte + RGBA(red)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat_data = zlib.compress(raw)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat_data)
        + chunk(b"IEND", b"")
    )


def _cleanup_avatar(avatar_url: str | None) -> None:
    """清理测试产生的头像文件。"""
    if not avatar_url:
        return
    filename = avatar_url.split("/")[-1]
    project_root = Path(__file__).resolve().parent.parent
    filepath = project_root / "uploads" / "avatars" / filename
    if filepath.exists():
        os.remove(filepath)


def _register_user(client: TestClient, phone: str, name: str) -> str:
    """注册用户并返回 access_token。"""
    resp = client.post("/api/v1/auth/register", json={"phone": phone, "name": name})
    assert resp.status_code == 200, f"注册失败: {resp.json()}"
    return resp.json()["data"]["access_token"]


def _upload_avatar(
    client: TestClient,
    token: str,
    image_bytes: bytes,
    content_type: str = "image/png",
) -> dict:
    """上传头像并返回完整响应 JSON。"""
    ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
    ext = ext_map.get(content_type, ".png")
    resp = client.post(
        "/api/v1/auth/avatar",
        files={"file": (f"avatar{ext}", image_bytes, content_type)},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp


# =============================================================================
# 测试用例
# =============================================================================


class TestAvatarUploadE2E:
    """头像上传与 JWT 同步完整 E2E 测试。"""

    def test_full_avatar_upload_and_jwt_sync(self):
        """完整流程：注册→/me 无头像→上传头像→响应含新 token→JWT claims 含 avatar_url→/me 返回一致→验证文件存在→清理。"""
        app = _make_app()
        client = TestClient(app)
        phone = "13900000100"
        name = "头像测试用户"

        # 1. 注册
        token = _register_user(client, phone, name)

        # 2. /me 返回 avatar_url=None
        me1 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me1.status_code == 200
        assert me1.json()["data"]["avatar_url"] is None, "新注册用户应无头像"

        # 3. 上传头像
        image_bytes = _make_test_image()
        upload_resp = _upload_avatar(client, token, image_bytes)
        assert upload_resp.status_code == 200, f"头像上传失败: {upload_resp.json()}"
        body = upload_resp.json()
        assert body["code"] == 0

        avatar_url = body["data"]["avatar_url"]
        assert avatar_url is not None, "应返回 avatar_url"
        assert avatar_url.startswith("/api/v1/uploads/avatars/"), f"avatar_url 格式异常: {avatar_url}"

        new_access_token = body["data"]["access_token"]
        new_refresh_token = body["data"]["refresh_token"]
        assert body["data"]["token_type"] == "Bearer"
        assert body["data"]["expires_in"] > 0

        # 4. 验证新 access token 的 claims 包含 avatar_url
        payload = pyjwt.decode(new_access_token, "test-secret", algorithms=["HS256"])
        assert payload.get("avatar_url") == avatar_url, "新 access token 的 claims 应包含 avatar_url"

        # 5. 用新 token 调 /me 验证 avatar_url 一致
        me2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access_token}"})
        assert me2.status_code == 200
        assert me2.json()["data"]["avatar_url"] == avatar_url, "/me 返回的 avatar_url 应与上传一致"

        # 6. 验证文件存在于磁盘且非空
        filename = avatar_url.split("/")[-1]
        project_root = Path(__file__).resolve().parent.parent
        filepath = project_root / "uploads" / "avatars" / filename
        assert filepath.exists(), f"头像文件未保存到磁盘: {filepath}"
        assert filepath.stat().st_size > 0, "头像文件大小应为正数"

        # 7. 清理
        os.remove(filepath)

    def test_avatar_url_in_jwt_claims(self):
        """上传头像后，新签发的 access_token 和 refresh_token 都应包含 avatar_url。"""
        app = _make_app()
        client = TestClient(app)

        token = _register_user(client, "13900000101", "JWT声明测试")
        image_bytes = _make_test_image()
        upload_resp = _upload_avatar(client, token, image_bytes)
        assert upload_resp.status_code == 200
        body = upload_resp.json()
        avatar_url = body["data"]["avatar_url"]

        # 解码 access_token 和 refresh_token
        access_payload = pyjwt.decode(body["data"]["access_token"], "test-secret", algorithms=["HS256"])
        refresh_payload = pyjwt.decode(body["data"]["refresh_token"], "test-secret", algorithms=["HS256"])

        # 两者都应包含 avatar_url
        assert access_payload.get("avatar_url") == avatar_url, "access_token claims 应包含 avatar_url"
        assert refresh_payload.get("avatar_url") == avatar_url, "refresh_token claims 应包含 avatar_url"

        # 清理
        _cleanup_avatar(avatar_url)

    def test_old_token_does_not_have_avatar(self):
        """上传前的旧 token 不应包含 avatar_url，上传后的新 token 应包含。"""
        app = _make_app()
        client = TestClient(app)

        # 注册并获取旧 token
        old_token = _register_user(client, "13900000102", "Token对比测试")

        # 旧 token 不应包含 avatar_url
        old_payload = pyjwt.decode(old_token, "test-secret", algorithms=["HS256"])
        assert old_payload.get("avatar_url") is None, "上传前签发的 token 不应包含 avatar_url"

        # 上传头像
        image_bytes = _make_test_image()
        upload_resp = _upload_avatar(client, old_token, image_bytes)
        assert upload_resp.status_code == 200
        body = upload_resp.json()
        avatar_url = body["data"]["avatar_url"]
        new_token = body["data"]["access_token"]

        # 新 token 应包含 avatar_url
        new_payload = pyjwt.decode(new_token, "test-secret", algorithms=["HS256"])
        assert new_payload.get("avatar_url") == avatar_url, "上传后签发的 token 应包含 avatar_url"

        # 清理
        _cleanup_avatar(avatar_url)

    def test_upload_different_image_formats(self):
        """不同图片格式（PNG/JPEG/GIF/WebP）上传均应成功。"""
        app = _make_app()
        client = TestClient(app)

        token = _register_user(client, "13900000103", "格式测试用户")

        # 各格式最小有效数据（服务端仅校验 content_type，不校验实际内容）
        formats = [
            ("image/png", _make_test_image()),
            ("image/jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 10),
            ("image/gif", b"GIF89a" + b"\x00" * 10),
            ("image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 10),
        ]

        avatar_urls: list[str] = []
        try:
            for content_type, image_data in formats:
                resp = _upload_avatar(client, token, image_data, content_type)
                assert resp.status_code == 200, f"{content_type} 上传失败: {resp.json()}"
                body = resp.json()
                assert body["code"] == 0
                assert body["data"]["avatar_url"] is not None
                avatar_urls.append(body["data"]["avatar_url"])
        finally:
            for url in avatar_urls:
                _cleanup_avatar(url)

    def test_upload_empty_file(self):
        """上传空文件（0 字节，image/png）应成功。"""
        app = _make_app()
        client = TestClient(app)

        token = _register_user(client, "13900000104", "空文件测试")
        resp = client.post(
            "/api/v1/auth/avatar",
            files={"file": ("empty.png", b"", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 0 字节文件通过类型检查，应成功
        assert resp.status_code == 200, f"空文件上传失败: {resp.json()}"
        body = resp.json()
        assert body["code"] == 0
        avatar_url = body["data"]["avatar_url"]
        assert avatar_url is not None

        # 清理
        _cleanup_avatar(avatar_url)

    def test_upload_without_file_field(self):
        """不传 file 字段应返回 422（验证错误）。"""
        app = _make_app()
        client = TestClient(app)

        token = _register_user(client, "13900000105", "缺文件测试")
        resp = client.post(
            "/api/v1/auth/avatar",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422, f"缺少 file 字段应返回 422: {resp.status_code}"

    def test_upload_with_invalid_token(self):
        """使用无效 token 上传应返回 401。"""
        app = _make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/v1/auth/avatar",
            files={"file": ("avatar.png", _make_test_image(), "image/png")},
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401, f"无效 token 应返回 401: {resp.status_code}"

    def test_avatar_persistence_across_sessions(self):
        """头像信息在不同登录会话中应持久存在。"""
        app = _make_app()
        client = TestClient(app)
        phone = "13900000106"
        name = "持久化测试"

        # 注册并上传头像
        token = _register_user(client, phone, name)
        image_bytes = _make_test_image()
        upload_resp = _upload_avatar(client, token, image_bytes)
        assert upload_resp.status_code == 200
        body = upload_resp.json()
        avatar_url = body["data"]["avatar_url"]

        try:
            # 重新登录（新会话，新 token）
            login_resp = client.post(
                "/api/v1/auth/login",
                json={"credential_type": "phone", "token": phone},
            )
            assert login_resp.status_code == 200
            new_token = login_resp.json()["data"]["access_token"]

            # 用新 token 调 /me，avatar_url 应一致
            me_resp = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {new_token}"},
            )
            assert me_resp.status_code == 200
            assert me_resp.json()["data"]["avatar_url"] == avatar_url, "跨会话 avatar_url 应保持不变"
        finally:
            _cleanup_avatar(avatar_url)

    def test_cache_priority_repo_over_cache(self):
        """验证 PhoneAuthProvider 优先从仓储查询而非缓存（修复缓存优先级 Bug）。

        场景：缓存中存有旧用户（无 avatar_url），仓储已更新为新用户（有 avatar_url）。
        登录时应返回仓储中的最新数据。
        """
        app = _make_app()
        client = TestClient(app)
        phone = "13900000107"
        name = "缓存优先级测试"

        # 1. 注册用户
        token = _register_user(client, phone, name)

        # 2. 上传头像
        image_bytes = _make_test_image()
        upload_resp = _upload_avatar(client, token, image_bytes)
        assert upload_resp.status_code == 200
        body = upload_resp.json()
        avatar_url = body["data"]["avatar_url"]

        try:
            # 3. 模拟缓存过期：直接清除 PhoneAuthProvider 的 _users 缓存
            auth_provider = app.state.server.auth_provider
            auth_provider._users.clear()  # 清空缓存，使仓储成为唯一数据源

            # 4. 重新登录 — 此时 authenticate() 必须查仓储才能找到用户
            login_resp = client.post(
                "/api/v1/auth/login",
                json={"credential_type": "phone", "token": phone},
            )
            assert login_resp.status_code == 200, f"缓存清空后登录失败: {login_resp.json()}"
            new_token = login_resp.json()["data"]["access_token"]

            # 5. 验证 /me 返回的 avatar_url 正确（说明 authenticate 从仓储获取了最新数据）
            me_resp = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {new_token}"},
            )
            assert me_resp.status_code == 200
            assert me_resp.json()["data"]["avatar_url"] == avatar_url, (
                f"缓存清空后跨会话 avatar_url 应一致, 期望 {avatar_url}, "
                f"实际 {me_resp.json()['data']['avatar_url']}"
            )
        finally:
            _cleanup_avatar(avatar_url)