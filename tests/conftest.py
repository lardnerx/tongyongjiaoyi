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
    "TEST_DATABASE_URL", "postgresql://umcp:umcp@localhost:5432/umcp_dev"
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
