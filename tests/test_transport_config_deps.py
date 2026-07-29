"""TransportConfig 和 deps 依赖注入测试。"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService, user_from_claims
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.deps import get_current_user, get_jwt_service, get_server


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
