"""TransportConfig 和 deps 依赖注入测试。"""

from __future__ import annotations

import os
import time

import pytest
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService, user_from_claims
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.deps import get_current_user, get_jwt_service, get_server
from umcp_core.transport.errors import ApiError


def _build_app_with_handler(server: UMCPServer, jwt_service: JwtService) -> FastAPI:
    """构建带 ApiError 异常处理器的测试 app。

    deps.get_current_user 失败时抛出 ApiError 子类（TokenExpiredError /
    InvalidCredentialError）。测试 app 需注册最小异常处理器将其映射为 HTTP 响应，
    以便断言 status_code 和错误码。这不依赖任务 7 的 register_exception_handlers。
    """
    app = FastAPI()
    app.state.server = server
    app.state.jwt_service = jwt_service

    @app.exception_handler(ApiError)
    async def _handle_api_error(request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "message": exc.message},
        )

    @app.get("/test")
    async def _endpoint(current: User = Depends(get_current_user)):
        return {"user_id": current.user_id}

    return app


class TestTransportConfig:
    def test_defaults(self):
        config = TransportConfig(jwt_secret="x")
        assert config.jwt_access_ttl == 3600
        assert config.jwt_refresh_ttl == 604800
        assert config.db_dsn is None
        assert config.cors_origins == ["*"]
        assert config.log_level == "INFO"
        assert config.host == "0.0.0.0"
        assert config.port == 8000

    def test_from_env_uses_env_vars(self, monkeypatch):
        monkeypatch.setenv("UMCP_JWT_SECRET", "env-secret")
        monkeypatch.setenv("UMCP_JWT_ACCESS_TTL", "1800")
        monkeypatch.setenv("UMCP_DB_DSN", "postgresql://localhost/test")
        monkeypatch.setenv("UMCP_CORS_ORIGINS", "http://a.com,http://b.com")
        monkeypatch.setenv("UMCP_HOST", "127.0.0.1")
        monkeypatch.setenv("UMCP_PORT", "9000")
        config = TransportConfig.from_env()
        assert config.jwt_secret == "env-secret"
        assert config.jwt_access_ttl == 1800
        assert config.db_dsn == "postgresql://localhost/test"
        assert config.cors_origins == ["http://a.com", "http://b.com"]
        assert config.host == "127.0.0.1"
        assert config.port == 9000

    def test_from_env_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("UMCP_JWT_SECRET", raising=False)
        with pytest.raises(ValueError, match="UMCP_JWT_SECRET"):
            TransportConfig.from_env()

    def test_from_env_invalid_int_raises(self, monkeypatch):
        """非整数环境变量应抛出包含变量名的 ValueError。"""
        monkeypatch.setenv("UMCP_JWT_SECRET", "env-secret")
        monkeypatch.setenv("UMCP_PORT", "abc")
        with pytest.raises(ValueError, match="UMCP_PORT"):
            TransportConfig.from_env()

    def test_from_env_invalid_jwt_access_ttl_raises(self, monkeypatch):
        """jwt_access_ttl 非整数也应抛出包含变量名的 ValueError。"""
        monkeypatch.setenv("UMCP_JWT_SECRET", "env-secret")
        monkeypatch.setenv("UMCP_JWT_ACCESS_TTL", "not-a-number")
        with pytest.raises(ValueError, match="UMCP_JWT_ACCESS_TTL"):
            TransportConfig.from_env()

    def test_from_env_invalid_jwt_refresh_ttl_raises(self, monkeypatch):
        """jwt_refresh_ttl 非整数也应抛出包含变量名的 ValueError。"""
        monkeypatch.setenv("UMCP_JWT_SECRET", "env-secret")
        monkeypatch.setenv("UMCP_JWT_REFRESH_TTL", "xyz")
        with pytest.raises(ValueError, match="UMCP_JWT_REFRESH_TTL"):
            TransportConfig.from_env()

    def test_from_env_cors_empty_string(self, monkeypatch):
        """空字符串 CORS → []（当前规格行为）。"""
        monkeypatch.setenv("UMCP_JWT_SECRET", "env-secret")
        monkeypatch.setenv("UMCP_CORS_ORIGINS", "")
        config = TransportConfig.from_env()
        assert config.cors_origins == []

    def test_from_env_cors_only_commas(self, monkeypatch):
        """仅有逗号的 CORS → []。"""
        monkeypatch.setenv("UMCP_JWT_SECRET", "env-secret")
        monkeypatch.setenv("UMCP_CORS_ORIGINS", ",,")
        config = TransportConfig.from_env()
        assert config.cors_origins == []

    def test_from_env_cors_with_spaces(self, monkeypatch):
        """带空格的 CORS 应被 strip。"""
        monkeypatch.setenv("UMCP_JWT_SECRET", "env-secret")
        monkeypatch.setenv("UMCP_CORS_ORIGINS", " a , b ")
        config = TransportConfig.from_env()
        assert config.cors_origins == ["a", "b"]


class TestDeps:
    def test_get_current_user_decodes_valid_token(self):
        server = UMCPServer()
        server.use_in_memory_repositories()
        jwt_service = JwtService(secret="test-secret")
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential("phone", "13800000000"))
        token = jwt_service.issue(user)["access_token"]

        app = FastAPI()
        app.state.server = server
        app.state.jwt_service = jwt_service

        @app.get("/test")
        async def _endpoint(current: User = Depends(get_current_user)):
            return {"user_id": current.user_id}

        client = TestClient(app)
        resp = client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == user.user_id

    def test_get_current_user_missing_token_returns_401(self):
        server = UMCPServer()
        server.use_in_memory_repositories()
        jwt_service = JwtService(secret="test-secret")

        app = FastAPI()
        app.state.server = server
        app.state.jwt_service = jwt_service

        @app.get("/test")
        async def _endpoint(current: User = Depends(get_current_user)):
            return {"user_id": current.user_id}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 401

    def test_get_current_user_expired_token_returns_401(self):
        """过期 token → TokenExpiredError (code 1002)。

        验证 deps.get_current_user 的 except 顺序正确：
        ExpiredSignatureError 是 InvalidTokenError 的子类，必须先捕获。
        """
        server = UMCPServer()
        server.use_in_memory_repositories()
        jwt_service = JwtService(secret="test-secret", access_ttl=1)
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential("phone", "13800000000"))
        token = jwt_service.issue(user)["access_token"]

        app = _build_app_with_handler(server, jwt_service)
        client = TestClient(app)

        time.sleep(2)
        resp = client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        # 过期 token 应映射为 TokenExpiredError (code 1002)，而非 InvalidCredentialError (1001)
        assert resp.json()["code"] == 1002

    def test_get_current_user_invalid_token_returns_401(self):
        """签名篡改/格式错误 token → InvalidCredentialError (code 1001)。"""
        server = UMCPServer()
        server.use_in_memory_repositories()
        jwt_service = JwtService(secret="test-secret")

        app = _build_app_with_handler(server, jwt_service)
        client = TestClient(app)

        resp = client.get(
            "/test", headers={"Authorization": "Bearer invalid.token.string"}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 1001

    def test_get_current_user_revoked_token_returns_401(self):
        """已吊销 token → InvalidCredentialError (code 1001)。"""
        server = UMCPServer()
        server.use_in_memory_repositories()
        jwt_service = JwtService(secret="test-secret")
        provider = PhoneAuthProvider()
        user = provider.authenticate(Credential("phone", "13800000000"))
        token = jwt_service.issue(user)["access_token"]

        # 解码拿 jti 并吊销
        payload = jwt_service.decode(token)
        jwt_service.revoke(payload["jti"])

        app = _build_app_with_handler(server, jwt_service)
        client = TestClient(app)

        resp = client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["code"] == 1001
