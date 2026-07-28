"""L4: 端到端持久化测试。

验证完整的启动→执行→重启→恢复→继续流程。
"""

from __future__ import annotations

import pytest

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.server import UMCPServer

# 注意：不使用模块级 pytestmark，以便 test_in_memory_path_unaffected 不被跳过。
# 各 PG 测试单独标记 @pytest.mark.postgres。


def _make_server(pg_bundle) -> UMCPServer:
    """构造带 PG 仓储的 server。"""
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
    """推进子任务经过完整生命周期到 COMPLETED。"""
    sub.publish()
    sub.assign_to("test_res")
    sub.start_execution()
    sub.complete()


class TestPersistenceE2E:
    @pytest.mark.postgres
    def test_task_persists_across_restart(self, pg_bundle):
        """任务应在"重启"后仍可查询。"""
        # server 1：创建任务
        server1 = _make_server(pg_bundle)
        task = StandardTask(
            demander_id="user-e2e-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="持久化测试",
        )
        server1.task_repo.save(task)
        task_id = task.task_id

        # 模拟重启：新 server 实例（同一 PG）
        server2 = _make_server(pg_bundle)
        found = server2.task_repo.find_by_id(task_id)
        assert found is not None
        assert found.demander_id == "user-e2e-1"
        assert found.title == "持久化测试"

    @pytest.mark.postgres
    def test_composite_recovers_and_continues(self, pg_bundle):
        """复合任务在"重启"后应恢复并继续执行。"""
        # server 1：创建复合任务，子任务未完成
        server1 = _make_server(pg_bundle)
        server1.register_subtask_executor("ride_hailing", _complete_subtask)

        sub_a = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        sub_a.task_id = "e2e-a"
        sub_b = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        sub_b.task_id = "e2e-b"
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )

        # 持久化（模拟中断前的状态）
        server1.task_repo.save(composite)
        server1.task_repo.save(sub_a)
        server1.task_repo.save(sub_b)

        # sub_a 已完成，sub_b 仍 DRAFT，composite 处于 MATCHING
        sub_a.status = TaskStatus.COMPLETED
        sub_b.status = TaskStatus.DRAFT
        composite.status = TaskStatus.MATCHING
        server1.task_repo.save(sub_a)
        server1.task_repo.save(sub_b)
        server1.task_repo.save(composite)

        # 模拟重启：新 server 实例
        server2 = _make_server(pg_bundle)
        server2.register_subtask_executor("ride_hailing", _complete_subtask)

        stats = server2.recover_composite_tasks()
        assert stats["recovered"] == 1
        assert stats["redispatched"] == 1

        # 验证最终状态
        recovered_composite = server2.task_repo.find_by_id(composite.task_id)
        assert recovered_composite.status == TaskStatus.COMPLETED
        recovered_b = server2.task_repo.find_by_id(sub_b.task_id)
        assert recovered_b.status == TaskStatus.COMPLETED

    @pytest.mark.postgres
    def test_event_log_persists(self, pg_bundle):
        """事件日志应持久化并支持回放。"""
        from umcp_core.events.bus import Event
        from umcp_core.events.types import EventType

        server1 = _make_server(pg_bundle)
        server1.event_bus.publish(
            Event(
                type=EventType.TASK_PUBLISHED,
                source_layer="L2",
                payload={"task_id": "evt-task-1"},
            )
        )

        # 模拟重启
        server2 = _make_server(pg_bundle)
        events = server2.event_repo.replay("evt-task-1")
        assert len(events) >= 1
        assert events[0].payload["task_id"] == "evt-task-1"

    @pytest.mark.postgres
    def test_transaction_atomicity(self, pg_bundle):
        """复合任务持久化应是原子的（失败回滚）。"""
        from umcp_core.repositories.postgres.models import TaskModel
        from umcp_core.repositories.postgres.converters import task_to_orm

        task = StandardTask(
            demander_id="user-tx-fail",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        task.task_id = "tx-fail-1"

        with pytest.raises(ValueError):
            with pg_bundle.transaction() as session:
                session.merge(task_to_orm(task))
                raise ValueError("模拟失败")

        # 验证未持久化
        found = pg_bundle.task_repo.find_by_id("tx-fail-1")
        assert found is None

    def test_in_memory_path_unaffected(self):
        """InMemory 路径应保持原行为（无 PG 依赖）。"""
        server = UMCPServer()
        server.use_in_memory_repositories()

        task = StandardTask(
            demander_id="user-mem",
            domain_tag=DomainTag.of("ride_hailing"),
        )
        server.task_repo.save(task)

        found = server.task_repo.find_by_id(task.task_id)
        assert found is not None
        assert found.demander_id == "user-mem"
