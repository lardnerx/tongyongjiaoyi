"""测试内存版 Repository 实现。

覆盖 src/umcp_core/repositories/in_memory.py 的所有仓储类与 RepositoryBundle。
使用真实对象（非 mock），每个测试独立构造数据。
"""

from __future__ import annotations

import pytest

from umcp_core.core import Deal, DomainTag, Resource, ResourceStatus, StandardTask, TaskStatus, User
from umcp_core.core.base import Demander, PermissionSet, Supplier
from umcp_core.core.domain import Credential
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l5 import Evaluation, TrustProfile
from umcp_core.repositories.in_memory import (
    InMemoryDealRepository,
    InMemoryEventRepository,
    InMemoryRepositoryBundle,
    InMemoryResourceRepository,
    InMemoryTaskRepository,
    InMemoryTrustRepository,
    InMemoryUserRepository,
)


# ----------------------------------------------------------------------
# 桩类：Task / Resource / User 的最小可实例化子类
# ----------------------------------------------------------------------


class _Task(StandardTask):
    def task_type(self) -> str:
        return "test_standard"


class _Resource(Resource):
    def resource_type(self) -> str:
        return "test_resource"


class _Demander(Demander):
    def __init__(self) -> None:
        self._perms = PermissionSet({"publish_task"})

    @property
    def permissions(self) -> PermissionSet:
        return self._perms


class _Supplier(Supplier):
    def __init__(self) -> None:
        self._perms = PermissionSet({"register_resource"})

    @property
    def permissions(self) -> PermissionSet:
        return self._perms


class _User(User):
    def authenticate(self, credential: Credential) -> bool:
        return True


# ----------------------------------------------------------------------
# 辅助工厂
# ----------------------------------------------------------------------


def _make_task(
    demander_id: str = "d1",
    domain: str = "ride",
    status: str = TaskStatus.DRAFT,
) -> _Task:
    task = _Task(demander_id=demander_id, domain_tag=DomainTag.of(domain))
    task.status = status
    return task


def _make_resource(
    supplier_id: str = "s1",
    domain: str = "ride",
    status: str = ResourceStatus.IDLE,
) -> _Resource:
    res = _Resource(supplier_id=supplier_id, domain_tag=DomainTag.of(domain))
    res.status = status
    return res


def _make_deal(
    task_id: str = "t1",
    resource_id: str = "r1",
    demander_id: str = "d1",
    supplier_id: str = "s1",
    status: str = "pending",
) -> Deal:
    deal = Deal(
        task_id=task_id,
        resource_id=resource_id,
        demander_id=demander_id,
        supplier_id=supplier_id,
    )
    deal.status = status
    return deal


def _make_user(user_id: str = "u1", name: str = "alice") -> _User:
    user = _User(user_id=user_id, name=name)
    user.add_role(_Demander())
    return user


# ----------------------------------------------------------------------
# InMemoryTaskRepository
# ----------------------------------------------------------------------


class TestInMemoryTaskRepository:
    def test_save_and_find_by_id(self):
        repo = InMemoryTaskRepository()
        task = _make_task()
        saved = repo.save(task)
        assert saved is task
        assert repo.find_by_id(task.task_id) is task

    def test_find_by_id_returns_none_when_absent(self):
        repo = InMemoryTaskRepository()
        assert repo.find_by_id("not-exist") is None

    def test_find_by_demander(self):
        repo = InMemoryTaskRepository()
        t1 = _make_task(demander_id="d1")
        t2 = _make_task(demander_id="d1")
        t3 = _make_task(demander_id="d2")
        for t in (t1, t2, t3):
            repo.save(t)
        result = repo.find_by_demander("d1")
        assert {t.task_id for t in result} == {t1.task_id, t2.task_id}

    def test_find_by_demander_empty(self):
        repo = InMemoryTaskRepository()
        assert repo.find_by_demander("nobody") == []

    def test_find_by_status_without_domain_filter(self):
        repo = InMemoryTaskRepository()
        t_draft = _make_task(status=TaskStatus.DRAFT)
        t_match = _make_task(status=TaskStatus.MATCHING)
        repo.save(t_draft)
        repo.save(t_match)
        result = repo.find_by_status(TaskStatus.DRAFT)
        assert [t.task_id for t in result] == [t_draft.task_id]

    def test_find_by_status_with_domain_tag_filter(self):
        repo = InMemoryTaskRepository()
        t_ride = _make_task(domain="ride", status=TaskStatus.MATCHING)
        t_design = _make_task(domain="design", status=TaskStatus.MATCHING)
        repo.save(t_ride)
        repo.save(t_design)
        result = repo.find_by_status(TaskStatus.MATCHING, domain_tag=DomainTag.of("ride"))
        assert [t.task_id for t in result] == [t_ride.task_id]

    def test_find_by_status_with_domain_tag_no_match(self):
        repo = InMemoryTaskRepository()
        repo.save(_make_task(domain="ride", status=TaskStatus.MATCHING))
        result = repo.find_by_status(TaskStatus.MATCHING, domain_tag=DomainTag.of("design"))
        assert result == []

    def test_update_status_success(self):
        repo = InMemoryTaskRepository()
        task = _make_task(status=TaskStatus.DRAFT)
        repo.save(task)
        repo.update_status(task.task_id, TaskStatus.MATCHING)
        assert task.status == TaskStatus.MATCHING
        assert repo.find_by_id(task.task_id).status == TaskStatus.MATCHING

    def test_update_status_raises_key_error_when_absent(self):
        repo = InMemoryTaskRepository()
        with pytest.raises(KeyError, match="任务不存在"):
            repo.update_status("ghost", TaskStatus.MATCHING)


# ----------------------------------------------------------------------
# InMemoryResourceRepository
# ----------------------------------------------------------------------


class TestInMemoryResourceRepository:
    def test_save_and_find_by_id(self):
        repo = InMemoryResourceRepository()
        res = _make_resource()
        saved = repo.save(res)
        assert saved is res
        assert repo.find_by_id(res.resource_id) is res

    def test_find_by_id_returns_none_when_absent(self):
        repo = InMemoryResourceRepository()
        assert repo.find_by_id("ghost") is None

    def test_find_by_supplier(self):
        repo = InMemoryResourceRepository()
        r1 = _make_resource(supplier_id="s1")
        r2 = _make_resource(supplier_id="s1")
        r3 = _make_resource(supplier_id="s2")
        for r in (r1, r2, r3):
            repo.save(r)
        result = repo.find_by_supplier("s1")
        assert {r.resource_id for r in result} == {r1.resource_id, r2.resource_id}

    def test_find_available_filters_by_domain_and_idle(self):
        repo = InMemoryResourceRepository()
        r_idle_ride = _make_resource(supplier_id="s1", domain="ride", status=ResourceStatus.IDLE)
        r_busy_ride = _make_resource(supplier_id="s2", domain="ride", status=ResourceStatus.BUSY)
        r_idle_design = _make_resource(supplier_id="s3", domain="design", status=ResourceStatus.IDLE)
        for r in (r_idle_ride, r_busy_ride, r_idle_design):
            repo.save(r)
        result = repo.find_available(DomainTag.of("ride"))
        assert [r.resource_id for r in result] == [r_idle_ride.resource_id]

    def test_find_available_empty_when_no_match(self):
        repo = InMemoryResourceRepository()
        repo.save(_make_resource(domain="ride", status=ResourceStatus.IDLE))
        assert repo.find_available(DomainTag.of("design")) == []

    def test_update_status_success(self):
        repo = InMemoryResourceRepository()
        res = _make_resource(status=ResourceStatus.IDLE)
        repo.save(res)
        repo.update_status(res.resource_id, ResourceStatus.BUSY)
        assert res.status == ResourceStatus.BUSY

    def test_update_status_raises_key_error_when_absent(self):
        repo = InMemoryResourceRepository()
        with pytest.raises(KeyError, match="资源不存在"):
            repo.update_status("ghost", ResourceStatus.BUSY)


# ----------------------------------------------------------------------
# InMemoryDealRepository
# ----------------------------------------------------------------------


class TestInMemoryDealRepository:
    def test_save_and_find_by_id(self):
        repo = InMemoryDealRepository()
        deal = _make_deal()
        saved = repo.save(deal)
        assert saved is deal
        assert repo.find_by_id(deal.deal_id) is deal

    def test_find_by_id_returns_none_when_absent(self):
        repo = InMemoryDealRepository()
        assert repo.find_by_id("ghost") is None

    def test_find_by_task(self):
        repo = InMemoryDealRepository()
        d1 = _make_deal(task_id="t1")
        d2 = _make_deal(task_id="t1")
        d3 = _make_deal(task_id="t2")
        for d in (d1, d2, d3):
            repo.save(d)
        result = repo.find_by_task("t1")
        assert {d.deal_id for d in result} == {d1.deal_id, d2.deal_id}

    def test_find_by_supplier(self):
        repo = InMemoryDealRepository()
        d1 = _make_deal(supplier_id="s1")
        d2 = _make_deal(supplier_id="s2")
        repo.save(d1)
        repo.save(d2)
        result = repo.find_by_supplier("s1")
        assert [d.deal_id for d in result] == [d1.deal_id]


# ----------------------------------------------------------------------
# InMemoryUserRepository
# ----------------------------------------------------------------------


class TestInMemoryUserRepository:
    def test_save_and_find_by_id(self):
        repo = InMemoryUserRepository()
        user = _make_user(user_id="u1", name="alice")
        saved = repo.save(user)
        assert saved is user
        assert repo.find_by_id("u1") is user

    def test_find_by_id_returns_none_when_absent(self):
        repo = InMemoryUserRepository()
        assert repo.find_by_id("ghost") is None

    def test_find_by_name(self):
        repo = InMemoryUserRepository()
        user = _make_user(user_id="u1", name="alice")
        repo.save(user)
        assert repo.find_by_name("alice") is user

    def test_find_by_name_returns_none_when_absent(self):
        repo = InMemoryUserRepository()
        assert repo.find_by_name("nobody") is None

    def test_find_by_name_skips_empty_name(self):
        """无 name 的用户不应进入 _by_name 索引。"""
        repo = InMemoryUserRepository()
        user = _User(user_id="u1", name="")
        repo.save(user)
        assert repo.find_by_name("") is None
        assert repo.find_by_id("u1") is user


# ----------------------------------------------------------------------
# InMemoryTrustRepository
# ----------------------------------------------------------------------


class TestInMemoryTrustRepository:
    def test_save_and_find_profile(self):
        repo = InMemoryTrustRepository()
        profile = TrustProfile(user_id="u1", overall_score=4.5)
        saved = repo.save_profile(profile)
        assert saved is profile
        assert repo.find_profile("u1") is profile

    def test_find_profile_returns_none_when_absent(self):
        repo = InMemoryTrustRepository()
        assert repo.find_profile("ghost") is None

    def test_save_evaluation_and_find(self):
        repo = InMemoryTrustRepository()
        ev1 = Evaluation(
            evaluator_id="d1",
            evaluatee_id="s1",
            task_id="t1",
            ratings={"punctuality": 5.0},
        )
        ev2 = Evaluation(
            evaluator_id="d2",
            evaluatee_id="s1",
            task_id="t2",
            ratings={"punctuality": 4.0},
        )
        repo.save_evaluation(ev1)
        repo.save_evaluation(ev2)
        result = repo.find_evaluations("s1")
        assert len(result) == 2
        assert result[0] is ev1
        assert result[1] is ev2

    def test_find_evaluations_empty(self):
        repo = InMemoryTrustRepository()
        assert repo.find_evaluations("nobody") == []

    def test_find_evaluations_returns_copy(self):
        """find_evaluations 返回的列表应是副本，外部修改不影响内部状态。"""
        repo = InMemoryTrustRepository()
        repo.save_evaluation(
            Evaluation(evaluator_id="d1", evaluatee_id="s1", task_id="t1", ratings={})
        )
        result = repo.find_evaluations("s1")
        result.clear()
        assert len(repo.find_evaluations("s1")) == 1


# ----------------------------------------------------------------------
# InMemoryEventRepository
# ----------------------------------------------------------------------


class TestInMemoryEventRepository:
    def test_append_and_replay_all(self):
        repo = InMemoryEventRepository()
        e1 = Event(type=EventType.TASK_PUBLISHED, source_layer="L2", payload={"task_id": "t1"})
        e2 = Event(type=EventType.TASK_ASSIGNED, source_layer="L3", payload={"task_id": "t1"})
        repo.append(e1)
        repo.append(e2)
        result = repo.replay()
        assert len(result) == 2
        assert result[0] is e1
        assert result[1] is e2

    def test_replay_returns_copy(self):
        repo = InMemoryEventRepository()
        repo.append(Event(type=EventType.TASK_PUBLISHED, source_layer="L2"))
        result = repo.replay()
        result.clear()
        assert len(repo.replay()) == 1

    def test_replay_filter_by_task_id(self):
        repo = InMemoryEventRepository()
        e_t1 = Event(type=EventType.TASK_PUBLISHED, source_layer="L2", payload={"task_id": "t1"})
        e_t2 = Event(type=EventType.TASK_PUBLISHED, source_layer="L2", payload={"task_id": "t2"})
        e_unrelated = Event(type=EventType.TASK_ASSIGNED, source_layer="L3", payload={"task_id": "t3"})
        for e in (e_t1, e_t2, e_unrelated):
            repo.append(e)
        result = repo.replay("t1")
        assert [e.event_id for e in result] == [e_t1.event_id]

    def test_replay_filter_by_deal_id(self):
        repo = InMemoryEventRepository()
        e_d1 = Event(type=EventType.PAYMENT_HELD, source_layer="L4", payload={"deal_id": "d1"})
        e_d2 = Event(type=EventType.PAYMENT_HELD, source_layer="L4", payload={"deal_id": "d2"})
        repo.append(e_d1)
        repo.append(e_d2)
        result = repo.replay("d1")
        assert [e.event_id for e in result] == [e_d1.event_id]

    def test_replay_filter_by_user_id(self):
        repo = InMemoryEventRepository()
        e_u1 = Event(
            type=EventType.TRUST_UPDATED, source_layer="L5", payload={"user_id": "u1"}
        )
        e_u2 = Event(
            type=EventType.TRUST_UPDATED, source_layer="L5", payload={"user_id": "u2"}
        )
        repo.append(e_u1)
        repo.append(e_u2)
        result = repo.replay("u1")
        assert [e.event_id for e in result] == [e_u1.event_id]

    def test_replay_no_match_returns_empty(self):
        repo = InMemoryEventRepository()
        repo.append(Event(type=EventType.TASK_PUBLISHED, source_layer="L2", payload={"task_id": "t1"}))
        assert repo.replay("ghost") == []


# ----------------------------------------------------------------------
# InMemoryRepositoryBundle
# ----------------------------------------------------------------------


class TestInMemoryRepositoryBundle:
    def test_bundle_provides_all_six_repos(self):
        bundle = InMemoryRepositoryBundle()
        assert isinstance(bundle.task_repo, InMemoryTaskRepository)
        assert isinstance(bundle.resource_repo, InMemoryResourceRepository)
        assert isinstance(bundle.deal_repo, InMemoryDealRepository)
        assert isinstance(bundle.user_repo, InMemoryUserRepository)
        assert isinstance(bundle.trust_repo, InMemoryTrustRepository)
        assert isinstance(bundle.event_repo, InMemoryEventRepository)

    def test_bundle_repos_are_independent_instances(self):
        bundle = InMemoryRepositoryBundle()
        # 各仓储应是独立实例，互不影响
        assert bundle.task_repo is not bundle.resource_repo
        assert bundle.deal_repo is not bundle.task_repo
        assert bundle.user_repo is not bundle.trust_repo
        assert bundle.event_repo is not bundle.task_repo

    def test_bundle_repos_functional(self):
        """端到端验证：通过 bundle 注入数据后能正确读取。"""
        bundle = InMemoryRepositoryBundle()
        task = _make_task()
        bundle.task_repo.save(task)
        assert bundle.task_repo.find_by_id(task.task_id) is task

        res = _make_resource()
        bundle.resource_repo.save(res)
        assert bundle.resource_repo.find_by_id(res.resource_id) is res

        deal = _make_deal(task_id=task.task_id, resource_id=res.resource_id)
        bundle.deal_repo.save(deal)
        assert bundle.deal_repo.find_by_id(deal.deal_id) is deal

        user = _make_user()
        bundle.user_repo.save(user)
        assert bundle.user_repo.find_by_id(user.user_id) is user

        profile = TrustProfile(user_id=user.user_id, overall_score=4.0)
        bundle.trust_repo.save_profile(profile)
        assert bundle.trust_repo.find_profile(user.user_id) is profile

        event = Event(
            type=EventType.TASK_PUBLISHED, source_layer="L2", payload={"task_id": task.task_id}
        )
        bundle.event_repo.append(event)
        assert len(bundle.event_repo.replay(task.task_id)) == 1
