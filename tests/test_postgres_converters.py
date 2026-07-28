"""L1: 转换器单元测试。

验证领域对象 ↔ ORM 模型双向转换的正确性。
不依赖数据库，纯函数测试。
"""

from __future__ import annotations

import pytest
from datetime import datetime

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask, TaskStatus, CustomTask
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l5 import Evaluation, TrustProfile
from umcp_core.repositories.postgres.converters import (
    composite_task_from_orm,
    deal_from_orm,
    deal_to_orm,
    dependencies_from_orm,
    dependencies_to_orm,
    evaluation_from_orm,
    evaluation_to_orm,
    event_from_orm,
    event_to_orm,
    task_from_orm,
    task_to_orm,
    trust_profile_from_orm,
    trust_profile_to_orm,
)
from umcp_core.repositories.postgres.models import (
    DealModel,
    EventModel,
    TaskModel,
    TrustEvaluationModel,
    TrustProfileModel,
)


class TestTaskConverter:
    def test_standard_task_roundtrip(self):
        """StandardTask to_orm → from_orm 应保留所有字段。"""
        task = StandardTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            title="打车到机场",
            description="紧急",
        )
        task.task_id = "task-123"
        task.status = TaskStatus.MATCHING
        task.assigned_resource_id = "res-456"
        task.custom_fields = {"pickup": "中关村"}
        task.created_at = datetime(2026, 7, 28, 10, 0, 0)
        task.updated_at = datetime(2026, 7, 28, 10, 5, 0)

        model = task_to_orm(task)
        assert model.task_id == "task-123"
        assert model.task_type == "standard"
        assert model.demander_id == "user-1"
        assert model.domain_tag == "ride_hailing"
        assert model.status == TaskStatus.MATCHING
        assert model.assigned_resource_id == "res-456"
        assert model.custom_fields == {"pickup": "中关村"}

        restored = task_from_orm(model)
        assert restored.task_id == "task-123"
        assert restored.task_type() == "standard"
        assert restored.demander_id == "user-1"
        assert restored.domain_tag.value == "ride_hailing"
        assert restored.status == TaskStatus.MATCHING
        assert restored.assigned_resource_id == "res-456"
        assert restored.custom_fields == {"pickup": "中关村"}

    def test_custom_task_roundtrip(self):
        """CustomTask to_orm → from_orm 应重建为 CustomTask。"""
        task = CustomTask(
            demander_id="user-2",
            domain_tag=DomainTag.of("group_buying"),
            title="设计服务",
        )
        model = task_to_orm(task)
        assert model.task_type == "custom"

        restored = task_from_orm(model)
        assert isinstance(restored, CustomTask)
        assert restored.task_type() == "custom"

    def test_composite_task_roundtrip(self):
        """CompositeTask 重建需额外传入 dependencies 和 subtasks。"""
        sub_a = StandardTask(
            demander_id="user-1", domain_tag=DomainTag.of("ride_hailing")
        )
        sub_b = StandardTask(
            demander_id="user-1", domain_tag=DomainTag.of("ride_hailing")
        )
        composite = CompositeTask(
            demander_id="user-1",
            domain_tag=DomainTag.of("ride_hailing"),
            subtasks=[sub_a, sub_b],
            dependencies={sub_b.task_id: [sub_a.task_id]},
        )

        model = task_to_orm(composite)
        assert model.task_type == "composite"

        # from_orm 只重建基本字段
        basic = task_from_orm(model)
        assert isinstance(basic, CompositeTask)

        # composite_task_from_orm 重建完整
        dep_models = dependencies_to_orm(
            composite.task_id, {sub_b.task_id: [sub_a.task_id]}
        )
        deps = dependencies_from_orm(dep_models)
        full = composite_task_from_orm(model, deps, [sub_a, sub_b])
        assert len(full.subtasks) == 2
        assert full.dependencies == {sub_b.task_id: [sub_a.task_id]}


class TestDealConverter:
    def test_deal_roundtrip(self):
        deal = Deal(
            task_id="task-1",
            resource_id="res-1",
            demander_id="user-1",
            supplier_id="sup-1",
            deal_id="deal-1",
            final_amount=99.50,
            metadata={"payment_method": "alipay"},
        )
        deal.status = DealStatus.ACTIVE

        model = deal_to_orm(deal)
        assert model.deal_id == "deal-1"
        assert model.final_amount == 99.50
        assert model.status == DealStatus.ACTIVE

        restored = deal_from_orm(model)
        assert restored.deal_id == "deal-1"
        assert restored.final_amount == 99.50
        assert restored.status == DealStatus.ACTIVE
        assert restored.metadata == {"payment_method": "alipay"}


class TestTrustProfileConverter:
    def test_trust_profile_roundtrip_with_domain(self):
        profile = TrustProfile(
            user_id="user-1",
            dimension_scores={"delivery": 0.9, "quality": 0.8},
            overall_score=0.85,
            domain_tag="ride_hailing",
        )

        model = trust_profile_to_orm(profile)
        assert model.user_id == "user-1"
        assert model.domain_tag == "ride_hailing"
        assert model.overall_score == 0.85

        restored = trust_profile_from_orm(model)
        assert restored.user_id == "user-1"
        assert restored.domain_tag == "ride_hailing"
        assert restored.overall_score == 0.85
        assert restored.dimension_scores == {"delivery": 0.9, "quality": 0.8}


class TestEvaluationConverter:
    def test_evaluation_roundtrip_with_domain(self):
        evaluation = Evaluation(
            evaluator_id="user-1",
            evaluatee_id="user-2",
            task_id="task-1",
            ratings={"quality": 0.9},
            comment="好评",
            domain_tag="ride_hailing",
        )

        model = evaluation_to_orm(evaluation)
        assert model.evaluator_id == "user-1"
        assert model.domain_tag == "ride_hailing"

        restored = evaluation_from_orm(model)
        assert restored.evaluator_id == "user-1"
        assert restored.domain_tag == "ride_hailing"
        assert restored.ratings == {"quality": 0.9}


class TestEventConverter:
    def test_event_roundtrip(self):
        event = Event(
            type=EventType.TASK_PUBLISHED,
            source_layer="L2",
            payload={"task_id": "task-1", "extra": "data"},
        )

        model = event_to_orm(event)
        assert model.event_type == "task.published"
        assert model.task_id == "task-1"
        assert model.payload["extra"] == "data"

        restored = event_from_orm(model)
        assert restored.type == EventType.TASK_PUBLISHED
        assert restored.payload["task_id"] == "task-1"
        assert restored.payload["extra"] == "data"


class TestDependenciesConverter:
    def test_dependencies_roundtrip(self):
        deps = {"b": ["a"], "c": ["a", "b"]}
        models = dependencies_to_orm("composite-1", deps)
        assert len(models) == 3

        restored = dependencies_from_orm(models)
        assert sorted(restored["b"]) == ["a"]
        assert sorted(restored["c"]) == ["a", "b"]
