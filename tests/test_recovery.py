"""L3: 复合任务智能恢复测试。

模拟 server 重启后，从 PostgreSQL 恢复未终态复合任务。
"""

from __future__ import annotations

import pytest
from datetime import datetime

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.events.bus import EventBus
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer

pytestmark = pytest.mark.postgres


def _make_subtask(task_id: str, domain: str = "ride_hailing") -> StandardTask:
    task = StandardTask(
        demander_id="user-1",
        domain_tag=DomainTag.of(domain),
    )
    task.task_id = task_id
    return task


def _make_server_with_pg(pg_bundle) -> UMCPServer:
    """构造带 PG 仓储的 server（不复用 pg_bundle 的 event_bus）。"""
    server = UMCPServer()
    server.task_repo = pg_bundle.task_repo
    server.resource_repo = pg_bundle.resource_repo
    server.deal_repo = pg_bundle.deal_repo
    server.user_repo = pg_bundle.user_repo
    server.trust_repo = pg_bundle.trust_repo
    server.event_repo = pg_bundle.event_repo
    server._postgres_bundle = pg_bundle
    server.event_bus.subscribe_all(server.event_repo.append)
    return server


def _complete_subtask(sub) -> None:
    """推进子任务经过完整生命周期到 COMPLETED（DRAFT → COMPLETED 非法，需逐步转移）。"""
    sub.publish()
    sub.assign_to("test_res")
    sub.start_execution()
    sub.complete()


class TestRecoverCompositeTasks:
    def test_recover_draft_subtask(self, pg_bundle):
        """DRAFT 子任务应被重新派发。"""
        server = _make_server_with_pg(pg_bundle)
        # 注册一个同步执行器（立即完成子任务）
        server.register_subtask_executor("ride_hailing", _complete_subtask)

        sub_a = _make_subtask("a")
        sub_b = _make_subtask("b")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )
        # 持久化
        server.task_repo.save(composite)
        server.task_repo.save(sub_a)
        server.task_repo.save(sub_b)

        # 模拟 sub_a 已完成，sub_b 仍 DRAFT
        sub_a.status = TaskStatus.COMPLETED
        server.task_repo.save(sub_a)
        sub_b.status = TaskStatus.DRAFT
        composite.status = TaskStatus.MATCHING
        server.task_repo.save(sub_b)
        server.task_repo.save(composite)

        # 恢复
        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["redispatched"] == 1

        # sub_b 应被派发并完成
        recovered_b = server.task_repo.find_by_id(sub_b.task_id)
        assert recovered_b.status == TaskStatus.COMPLETED
        # 复合任务应完成
        recovered_c = server.task_repo.find_by_id(composite.task_id)
        assert recovered_c.status == TaskStatus.COMPLETED

    def test_recover_skips_terminal_composite(self, pg_bundle):
        """已终态的复合任务应跳过。"""
        server = _make_server_with_pg(pg_bundle)
        server.register_subtask_executor("ride_hailing", _complete_subtask)

        sub = _make_subtask("x")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub],
        )
        # 全部设为终态
        sub.status = TaskStatus.COMPLETED
        composite.status = TaskStatus.COMPLETED
        server.task_repo.save(composite)
        server.task_repo.save(sub)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 0

    def test_recover_marks_in_progress_as_timeout(self, pg_bundle):
        """IN_PROGRESS 子任务应标记 _pending_timeout。"""
        server = _make_server_with_pg(pg_bundle)

        sub = _make_subtask("p")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub],
        )
        sub.status = TaskStatus.IN_PROGRESS
        composite.status = TaskStatus.MATCHING
        server.task_repo.save(composite)
        server.task_repo.save(sub)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["marked_timeout"] == 1
        assert stats["redispatched"] == 0

        recovered = server.task_repo.find_by_id(sub.task_id)
        assert "_pending_timeout" in recovered.custom_fields

    def test_recover_returns_empty_when_no_composites(self, pg_bundle):
        """无复合任务时返回全 0 统计。"""
        server = _make_server_with_pg(pg_bundle)
        stats = server.recover_composite_tasks()
        assert stats == {"recovered": 0, "redispatched": 0, "marked_timeout": 0}

    def test_recover_multiple_composites(self, pg_bundle):
        """多个复合任务应串行恢复。"""
        server = _make_server_with_pg(pg_bundle)
        server.register_subtask_executor("ride_hailing", _complete_subtask)

        for i in range(3):
            sub = _make_subtask(f"multi-{i}")
            composite = CompositeTask(
                demander_id="user-1",
                domain_tag=DomainTag.of("ride_hailing"),
                subtasks=[sub],
            )
            server.task_repo.save(composite)
            server.task_repo.save(sub)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 3
        assert stats["redispatched"] == 3

    def test_recover_completes_when_all_subtasks_terminal(self, pg_bundle):
        """恢复后所有子任务终态时应完成父任务。"""
        server = _make_server_with_pg(pg_bundle)

        sub_a = _make_subtask("ca")
        sub_b = _make_subtask("cb")
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )
        sub_a.status = TaskStatus.COMPLETED
        sub_b.status = TaskStatus.COMPLETED
        composite.status = TaskStatus.MATCHING
        server.task_repo.save(composite)
        server.task_repo.save(sub_a)
        server.task_repo.save(sub_b)

        stats = server.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["redispatched"] == 0  # 都已终态，无需派发

        recovered = server.task_repo.find_by_id(composite.task_id)
        assert recovered.status == TaskStatus.COMPLETED
