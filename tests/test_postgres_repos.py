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


from umcp_core.core.resource import Resource, ResourceStatus, Capability


class _TestResource(Resource):
    """测试用 Resource 子类。"""

    def resource_type(self) -> str:
        return "test_resource"


@pytest.fixture
def resource_repo(pg_bundle):
    return pg_bundle.resource_repo


class TestPostgresResourceRepository:
    def test_save_and_find_by_id(self, resource_repo):
        cap = Capability(type="certification", name="business_license", verified=True)
        res = _TestResource(
            supplier_id="sup-1",
            domain_tag=DomainTag.of("ride_hailing"),
            capabilities=[cap],
            metadata={"location": "北京"},
        )
        resource_repo.save(res)

        found = resource_repo.find_by_id(res.resource_id)
        assert found is not None
        assert found.supplier_id == "sup-1"
        assert found.domain_tag.value == "ride_hailing"
        assert len(found.capabilities) == 1
        assert found.capabilities[0].name == "business_license"
        assert found.capabilities[0].verified is True
        assert found.metadata == {"location": "北京"}

    def test_find_by_id_nonexistent(self, resource_repo):
        assert resource_repo.find_by_id("nonexistent") is None

    def test_find_by_supplier(self, resource_repo):
        r1 = _TestResource(supplier_id="sup-A", domain_tag=DomainTag.of("ride_hailing"))
        r2 = _TestResource(supplier_id="sup-B", domain_tag=DomainTag.of("ride_hailing"))
        for r in [r1, r2]:
            resource_repo.save(r)

        results = resource_repo.find_by_supplier("sup-A")
        assert len(results) == 1
        assert results[0].supplier_id == "sup-A"

    def test_find_available_by_domain(self, resource_repo):
        r1 = _TestResource(supplier_id="sup-1", domain_tag=DomainTag.of("ride_hailing"))
        r1.status = ResourceStatus.IDLE
        r2 = _TestResource(supplier_id="sup-2", domain_tag=DomainTag.of("group_buying"))
        r2.status = ResourceStatus.IDLE
        for r in [r1, r2]:
            resource_repo.save(r)

        results = resource_repo.find_available(DomainTag.of("ride_hailing"))
        assert len(results) == 1
        assert results[0].domain_tag.value == "ride_hailing"

    def test_update_status(self, resource_repo):
        res = _TestResource(supplier_id="sup-1", domain_tag=DomainTag.of("ride_hailing"))
        resource_repo.save(res)

        resource_repo.update_status(res.resource_id, ResourceStatus.BUSY)

        found = resource_repo.find_by_id(res.resource_id)
        assert found.status == ResourceStatus.BUSY

    def test_update_status_nonexistent_raises(self, resource_repo):
        with pytest.raises(KeyError):
            resource_repo.update_status("nonexistent", "idle")


from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.base import User, Demander, PermissionSet, Supplier


class _TestUser(User):
    """测试用 User 子类。"""

    def __init__(self, user_id, name, metadata=None):
        super().__init__(user_id=user_id, name=name, metadata=metadata)

    def authenticate(self, credential) -> bool:
        return True


class _TestDemander(Demander):
    @property
    def permissions(self) -> PermissionSet:
        return PermissionSet({"create_task"})


@pytest.fixture
def deal_repo(pg_bundle):
    return pg_bundle.deal_repo


@pytest.fixture
def user_repo(pg_bundle):
    return pg_bundle.user_repo


class TestPostgresDealRepository:
    def test_save_and_find_by_id(self, deal_repo):
        deal = Deal(
            task_id="task-1",
            resource_id="res-1",
            demander_id="user-1",
            supplier_id="sup-1",
            final_amount=88.88,
        )
        deal_repo.save(deal)

        found = deal_repo.find_by_id(deal.deal_id)
        assert found is not None
        assert found.task_id == "task-1"
        assert found.final_amount == 88.88
        assert found.status == DealStatus.PENDING

    def test_find_by_task(self, deal_repo):
        d1 = Deal(task_id="task-A", resource_id="r1", demander_id="u1", supplier_id="s1")
        d2 = Deal(task_id="task-A", resource_id="r2", demander_id="u1", supplier_id="s2")
        d3 = Deal(task_id="task-B", resource_id="r3", demander_id="u2", supplier_id="s3")
        for d in [d1, d2, d3]:
            deal_repo.save(d)

        results = deal_repo.find_by_task("task-A")
        assert len(results) == 2

    def test_find_by_supplier(self, deal_repo):
        d1 = Deal(task_id="t1", resource_id="r1", demander_id="u1", supplier_id="sup-A")
        d2 = Deal(task_id="t2", resource_id="r2", demander_id="u2", supplier_id="sup-B")
        for d in [d1, d2]:
            deal_repo.save(d)

        results = deal_repo.find_by_supplier("sup-A")
        assert len(results) == 1


class TestPostgresUserRepository:
    def test_save_and_find_by_id(self, user_repo):
        user = _TestUser(user_id="u-1", name="张三")
        user.add_role(_TestDemander())
        user_repo.save(user)

        found = user_repo.find_by_id("u-1")
        assert found is not None
        assert found.name == "张三"
        assert "demander" in found.roles

    def test_find_by_name(self, user_repo):
        user = _TestUser(user_id="u-1", name="李四")
        user_repo.save(user)

        found = user_repo.find_by_name("李四")
        assert found is not None
        assert found.user_id == "u-1"

    def test_find_by_id_nonexistent(self, user_repo):
        assert user_repo.find_by_id("nonexistent") is None


from umcp_core.layers.l5 import TrustProfile, Evaluation


@pytest.fixture
def trust_repo(pg_bundle):
    return pg_bundle.trust_repo


class TestPostgresTrustRepository:
    def test_save_and_find_by_domain(self, trust_repo):
        profile = TrustProfile(
            user_id="user-1",
            dimension_scores={"delivery": 0.9, "quality": 0.8},
            overall_score=0.85,
            domain_tag="ride_hailing",
        )
        trust_repo.save_profile(profile)

        found = trust_repo.find_profile_by_domain("user-1", "ride_hailing")
        assert found is not None
        assert found.user_id == "user-1"
        assert found.domain_tag == "ride_hailing"
        assert found.overall_score == 0.85
        assert found.dimension_scores == {"delivery": 0.9, "quality": 0.8}

    def test_domain_isolation(self, trust_repo):
        """同一用户不同 domain 的信任档案应隔离存储。"""
        profile_ride = TrustProfile(
            user_id="user-1",
            overall_score=0.85,
            domain_tag="ride_hailing",
        )
        profile_buy = TrustProfile(
            user_id="user-1",
            overall_score=0.60,
            domain_tag="group_buying",
        )
        trust_repo.save_profile(profile_ride)
        trust_repo.save_profile(profile_buy)

        found_ride = trust_repo.find_profile_by_domain("user-1", "ride_hailing")
        found_buy = trust_repo.find_profile_by_domain("user-1", "group_buying")
        assert found_ride.overall_score == 0.85
        assert found_buy.overall_score == 0.60

    def test_find_by_domain_nonexistent(self, trust_repo):
        assert trust_repo.find_profile_by_domain("nobody", "ride_hailing") is None

    def test_find_profile_returns_any(self, trust_repo):
        """find_profile 向后兼容：返回任意 domain 的 profile。"""
        profile = TrustProfile(
            user_id="user-1",
            overall_score=0.7,
            domain_tag="ride_hailing",
        )
        trust_repo.save_profile(profile)

        found = trust_repo.find_profile("user-1")
        assert found is not None
        assert found.user_id == "user-1"

    def test_save_and_find_evaluations(self, trust_repo):
        eval1 = Evaluation(
            evaluator_id="u1",
            evaluatee_id="u2",
            task_id="t1",
            ratings={"quality": 0.9},
            domain_tag="ride_hailing",
        )
        trust_repo.save_evaluation(eval1)

        results = trust_repo.find_evaluations("u2")
        assert len(results) == 1
        assert results[0].ratings == {"quality": 0.9}
        assert results[0].domain_tag == "ride_hailing"

    def test_find_evaluations_empty(self, trust_repo):
        assert trust_repo.find_evaluations("nobody") == []
