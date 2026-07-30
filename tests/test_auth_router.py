"""auth router 集成测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from umcp_core.core.domain import Credential
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService
from umcp_core.transport.errors import register_exception_handlers
from umcp_core.transport.routers.auth import router


def _make_app() -> FastAPI:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    jwt_service = JwtService(secret="test-secret")

    app = FastAPI()
    app.state.server = server
    app.state.jwt_service = jwt_service
    app.include_router(router, prefix="/api/v1/auth")
    register_exception_handlers(app)
    return app


class TestLogin:
    def test_login_returns_tokens(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]
        assert body["data"]["token_type"] == "Bearer"

    def test_login_invalid_credential_type(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "unknown", "token": "x"},
        )
        # PhoneAuthProvider 不支持 unknown 类型 → 抛 ValueError → AuthRouter 转为 InvalidCredentialError
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 1001


class TestMe:
    def test_me_with_valid_token(self):
        app = _make_app()
        client = TestClient(app)
        # 先登录
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        token = login_resp.json()["data"]["access_token"]
        # 调 /me
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["name"] == "13800000000"

    def test_me_without_token_returns_401(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token_returns_401(self):
        """/me 用无效 token 应返回 401。"""
        app = _make_app()
        client = TestClient(app)
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.string"},
        )
        assert resp.status_code == 401


class TestLogout:
    def test_logout_returns_ok(self):
        app = _make_app()
        client = TestClient(app)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        token = login_resp.json()["data"]["access_token"]
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_logout_revokes_token(self):
        """登出后用同一 token 访问 /me 应返回 401。"""
        app = _make_app()
        client = TestClient(app)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        # 登出
        logout_resp = client.post("/api/v1/auth/logout", headers=headers)
        assert logout_resp.status_code == 200
        # 再用同一 token 访问 /me 应 401（token 已吊销）
        me_resp = client.get("/api/v1/auth/me", headers=headers)
        assert me_resp.status_code == 401
        assert me_resp.json()["code"] == 1001  # InvalidCredentialError

    def test_logout_revokes_refresh_token(self):
        """登出后 access 和 refresh 的 jti 都应在黑名单中。"""
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
        # 解码拿 jti 用于断言
        jwt_service = app.state.jwt_service
        access_payload = jwt_service.decode(access_token)
        refresh_payload = jwt_service.decode(refresh_token)
        access_jti = access_payload["jti"]
        refresh_jti = access_payload["refresh_jti"]
        assert refresh_jti == refresh_payload["jti"]  # 任务1的保证
        # 登出前：均未吊销
        assert not jwt_service.is_revoked(access_jti)
        assert not jwt_service.is_revoked(refresh_jti)
        # 登出
        logout_resp = client.post("/api/v1/auth/logout", headers=headers)
        assert logout_resp.status_code == 200
        # 登出后：两者均已吊销
        assert jwt_service.is_revoked(access_jti)
        assert jwt_service.is_revoked(refresh_jti)


class TestRefresh:
    def test_refresh_returns_new_access_token(self):
        app = _make_app()
        client = TestClient(app)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        refresh_token = login_resp.json()["data"]["refresh_token"]
        resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body["data"]

    def test_refresh_with_access_token_returns_401(self):
        """refresh 端点用 access_token（type!="refresh"）应返回 401。"""
        app = _make_app()
        client = TestClient(app)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"credential_type": "phone", "token": "13800000000"},
        )
        access_token = login_resp.json()["data"]["access_token"]
        resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access_token},  # 用 access_token 而非 refresh_token
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 1001

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
