"""测试核心抽象类：User、Role、Task、Resource、Deal。"""

from __future__ import annotations

import pytest

from umcp_core.core import (
    Capability,
    CustomTask,
    Deal,
    DomainTag,
    PackageTask,
    Resource,
    ResourceStatus,
    StandardTask,
    Task,
    TaskStatus,
    User,
)
from umcp_core.core.base import Demander, PermissionSet, Supplier


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


class _TestUser(User):
    def authenticate(self, credential) -> bool:  # type: ignore[override]
        return True


class _TestTask(StandardTask):
    def task_type(self) -> str:
        return "test_standard"


class _TestResource(Resource):
    def resource_type(self) -> str:
        return "test_resource"


class TestUser:
    def test_user_creation_with_default_id(self):
        user = _TestUser(name="alice")
        assert user.user_id.startswith("u_")
        assert user.name == "alice"
        assert user.active_role is None

    def test_user_add_role_auto_activates_first(self):
        user = _TestUser(name="alice")
        demander = _Demander()
        user.add_role(demander)
        assert user.active_role is demander
        assert user.is_demander()

    def test_user_switch_role(self):
        user = _TestUser(name="alice")
        demander = _Demander()
        supplier = _Supplier()
        user.add_role(demander)
        user.add_role(supplier)
        assert user.active_role is demander

        user.switch_role("supplier")
        assert user.active_role is supplier
        assert user.is_supplier()

    def test_user_switch_unknown_role_raises(self):
        user = _TestUser(name="alice")
        with pytest.raises(ValueError, match="未关联角色"):
            user.switch_role("supplier")


class TestTask:
    def test_standard_task_creation(self):
        task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        assert task.task_id.startswith("task_")
        assert task.status == TaskStatus.DRAFT
        assert task.task_type() == "test_standard"

    def test_task_publish_transitions_to_matching(self):
        task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        task.publish()
        assert task.status == TaskStatus.MATCHING

    def test_task_assign(self):
        task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        task.publish()
        task.assign_to("res_1")
        assert task.status == TaskStatus.ASSIGNED
        assert task.assigned_resource_id == "res_1"

    def test_task_complete(self):
        task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        task.publish()
        task.assign_to("res_1")
        task.start_execution()
        task.complete()
        assert task.status == TaskStatus.COMPLETED

    def test_task_cancel_from_any_non_terminal_state(self):
        task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        task.publish()
        task.cancel()
        assert task.status == TaskStatus.CANCELLED

    def test_task_cancel_terminal_raises(self):
        task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        task.publish()
        task.cancel()
        with pytest.raises(RuntimeError, match="已处于终态"):
            task.cancel()

    def test_invalid_transition_raises(self):
        task = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        with pytest.raises(ValueError, match="非法状态转移"):
            task.start_execution()  # DRAFT -> IN_PROGRESS 非法

    def test_custom_task_with_budget(self):
        task = CustomTask(
            demander_id="u1",
            domain_tag=DomainTag.of("design"),
            budget_min=100.0,
            budget_max=500.0,
        )
        assert task.budget_min == 100.0
        assert task.budget_max == 500.0
        assert task.task_type() == "custom"

    def test_custom_task_submit_proposal(self):
        task = CustomTask(demander_id="u1", domain_tag=DomainTag.of("design"))
        task.submit_proposal("supplier_1", 250.0, {"proposal": "mock"})
        assert len(task.proposals) == 1
        assert task.proposals[0]["supplier_id"] == "supplier_1"

    def test_package_task(self):
        std = _TestTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        custom = CustomTask(demander_id="u1", domain_tag=DomainTag.of("design"))
        package = PackageTask(
            demander_id="u1",
            domain_tag=DomainTag.of("mixed"),
            standard_sub_tasks=[std],
            custom_sub_task=custom,
        )
        assert len(package.standard_sub_tasks) == 1
        assert package.custom_sub_task is not None
        assert package.task_type() == "package"


class TestResource:
    def test_resource_creation(self):
        res = _TestResource(supplier_id="s1", domain_tag=DomainTag.of("ride"))
        assert res.resource_id.startswith("res_")
        assert res.status == ResourceStatus.OFFLINE

    def test_resource_register(self):
        res = _TestResource(supplier_id="s1", domain_tag=DomainTag.of("ride"))
        res.register()
        assert res.status == ResourceStatus.IDLE
        assert res.is_available()

    def test_resource_disabled_cannot_register(self):
        res = _TestResource(supplier_id="s1", domain_tag=DomainTag.of("ride"))
        res.update_status(ResourceStatus.DISABLED)
        with pytest.raises(RuntimeError, match="已被禁用"):
            res.register()

    def test_capability_validation(self):
        from datetime import datetime, timedelta

        valid_cap = Capability(
            type="certification",
            name="driver_license",
            value="C1",
            verified=True,
            expiry=datetime.utcnow() + timedelta(days=365),
        )
        expired_cap = Capability(
            type="certification",
            name="medical_cert",
            verified=True,
            expiry=datetime.utcnow() - timedelta(days=1),
        )
        res = _TestResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("ride"),
            capabilities=[valid_cap, expired_cap],
        )
        assert res.has_capability("driver_license")
        assert not res.has_capability("medical_cert")  # 过期

    def test_validate_capability(self):
        cap = Capability(type="skill", name="driving", verified=True)
        res = _TestResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("ride"),
            capabilities=[cap],
        )
        query = Capability(type="skill", name="driving", verified=True)
        assert res.validate_capability(query)

        missing = Capability(type="skill", name="cooking", verified=True)
        assert not res.validate_capability(missing)


class TestDeal:
    def test_deal_lifecycle(self):
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
            final_amount=100.0,
        )
        assert deal.status == "pending"

        deal.activate()
        assert deal.status == "active"

        deal.complete()
        assert deal.status == "completed"
        assert deal.completed_at is not None

    def test_deal_cancel(self):
        deal = Deal(task_id="t1", resource_id="r1", demander_id="d1", supplier_id="s1")
        deal.cancel()
        assert deal.status == "cancelled"

    def test_deal_dispute_flow(self):
        deal = Deal(task_id="t1", resource_id="r1", demander_id="d1", supplier_id="s1")
        deal.activate()
        deal.open_dispute()
        assert deal.status == "disputed"

        deal.resolve(outcome="cancelled")
        assert deal.status == "cancelled"

    def test_deal_cancel_terminal_raises(self):
        deal = Deal(task_id="t1", resource_id="r1", demander_id="d1", supplier_id="s1")
        deal.activate()
        deal.complete()
        with pytest.raises(RuntimeError, match="已处于终态"):
            deal.cancel()
