"""pytest 全局 fixture。

PG 测试需要 PostgreSQL 服务：
    docker compose up -d postgres
    export TEST_DATABASE_URL=postgresql://umcp:umcp@localhost:5432/umcp_dev
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# PG 测试标记
def pytest_configure(config):
    config.addinivalue_line("markers", "postgres: 需要 PostgreSQL 服务的测试")


# 无 PG 服务时跳过 PG 测试
PG_TEST_DSN = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://umcp:umcp@localhost:5432/umcp_dev"
)


def _pg_available() -> bool:
    try:
        from umcp_core.repositories.postgres.models import Base
        engine = create_engine(PG_TEST_DSN, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        Base.metadata.create_all(engine)
        engine.dispose()
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


def pytest_collection_modifyitems(config, items):
    """无 PG 服务时自动跳过标记为 postgres 的测试。"""
    if PG_AVAILABLE:
        return
    skip_pg = pytest.mark.skip(reason="PostgreSQL 不可用，设置 TEST_DATABASE_URL 并启动服务")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip_pg)


@pytest.fixture(scope="session")
def pg_engine():
    """会话级 PostgreSQL 引擎。"""
    from umcp_core.repositories.postgres.models import Base

    engine = create_engine(PG_TEST_DSN, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_bundle(pg_engine):
    """函数级仓储套件，测试后清空数据。"""
    from umcp_core.repositories.postgres.bundle import PostgresRepositoryBundle
    from umcp_core.repositories.postgres.models import Base

    bundle = PostgresRepositoryBundle(PG_TEST_DSN)
    yield bundle
    # 清空所有表（保证测试隔离）
    with bundle.engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE"))
        conn.commit()
    bundle.dispose()


# ---------- HTTP 传输层 fixtures（阶段五B）----------

@pytest.fixture
def jwt_service():
    """JwtService 单例（测试用短 TTL）。"""
    from umcp_core.transport.auth import JwtService
    return JwtService(secret="test-secret", access_ttl=60)


@pytest.fixture
def http_app():
    """带内存仓储和插件的 FastAPI 应用。"""
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.layers.l3 import InstantMatch, MatchResult
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.config import TransportConfig

    class _StubResource(Resource):
        def __init__(self):
            super().__init__(
                supplier_id="supplier_1",
                domain_tag=DomainTag.of("ride"),
                resource_id="res_1",
            )
            self.status = ResourceStatus.IDLE

        def resource_type(self) -> str:
            return "stub"

    class _StubMatchStrategy(InstantMatch):
        def execute(self, task, candidates):
            return MatchResult(
                task_id=task.task_id,
                selected_resource_id="res_1",
                candidates=[r.resource_id for r in candidates],
            )

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    server.register_match_strategy("ride", _StubMatchStrategy())
    server.resource_repo.save(_StubResource())
    config = TransportConfig(jwt_secret="test-secret")
    return create_app(server, config)


@pytest.fixture
def client(http_app):
    """TestClient（依赖 http_app）。"""
    from fastapi.testclient import TestClient
    return TestClient(http_app)


@pytest.fixture
def authed_client(client, jwt_service):
    """预登录的 TestClient，Authorization header 已设置。"""
    from umcp_core.core.domain import Credential
    from umcp_core.layers.l1 import PhoneAuthProvider
    user = PhoneAuthProvider().authenticate(Credential("phone", "13800000000"))
    token = jwt_service.issue(user)["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
