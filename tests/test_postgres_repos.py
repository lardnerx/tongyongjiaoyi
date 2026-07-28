"""L2: PostgreSQL 仓储 CRUD 测试。

需要 PostgreSQL 服务。通过 TEST_DATABASE_URL 环境变量配置连接。
默认连接 docker-compose 提供的 umcp_dev 数据库。
"""

from __future__ import annotations

import os
import pytest
from datetime import datetime

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus, CustomTask

pytestmark = pytest.mark.postgres


@pytest.fixture
def task_repo(pg_bundle):
    return pg_bundle.task_repo


class TestPostgresTaskRepository:
    def test_save_and_find_by_id(self, task_repo):
        task = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="打车",
        )
        task_id = task.task_id
        task_repo.save(task)

        found = task_repo.find_by_id(task_id)
        assert found is not None
        assert found.task_id == task_id
        assert found.demander_id == "user-1"
        assert found.status == TaskStatus.DRAFT
        assert found.title == "打车"

    def test_find_by_id_nonexistent_returns_none(self, task_repo):
        assert task_repo.find_by_id("nonexistent-id") is None

    def test_save_upsert(self, task_repo):
        """同一 task_id 二次 save 应更新而非插入。"""
        task = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="原标题",
        )
        task_repo.save(task)

        task.title = "新标题"
        task.status = TaskStatus.MATCHING
        task_repo.save(task)

        found = task_repo.find_by_id(task.task_id)
        assert found.title == "新标题"
        assert found.status == TaskStatus.MATCHING

    def test_find_by_demander(self, task_repo):
        t1 = StandardTask(demander_id="user-A", domain_tag=DomainTag.of("ride_hailing"))
        t2 = CustomTask(demander_id="user-A", domain_tag=DomainTag.of("group_buying"))
        t3 = StandardTask(demander_id="user-B", domain_tag=DomainTag.of("ride_hailing"))
        for t in [t1, t2, t3]:
            task_repo.save(t)

        results = task_repo.find_by_demander("user-A")
        assert len(results) == 2
        assert all(t.demander_id == "user-A" for t in results)

    def test_find_by_status_without_domain(self, task_repo):
        t1 = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride_hailing"))
        t2 = StandardTask(demander_id="u2", domain_tag=DomainTag.of("group_buying"))
        for t in [t1, t2]:
            task_repo.save(t)

        results = task_repo.find_by_status(TaskStatus.DRAFT)
        assert len(results) >= 2

    def test_find_by_status_with_domain_filter(self, task_repo):
        t1 = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride_hailing"))
        t2 = StandardTask(demander_id="u2", domain_tag=DomainTag.of("group_buying"))
        for t in [t1, t2]:
            task_repo.save(t)

        results = task_repo.find_by_status(
            TaskStatus.DRAFT, DomainTag.of("ride_hailing")
        )
        assert len(results) == 1
        assert results[0].domain_tag.value == "ride_hailing"

    def test_update_status(self, task_repo):
        task = StandardTask(demander_id="u1", domain_tag=DomainTag.of("ride_hailing"))
        task_repo.save(task)

        task_repo.update_status(task.task_id, TaskStatus.MATCHING)

        found = task_repo.find_by_id(task.task_id)
        assert found.status == TaskStatus.MATCHING

    def test_update_status_nonexistent_raises(self, task_repo):
        with pytest.raises(KeyError):
            task_repo.update_status("nonexistent", "completed")
