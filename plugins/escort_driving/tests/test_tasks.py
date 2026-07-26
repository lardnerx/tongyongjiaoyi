"""测试 EscortTask。"""

from __future__ import annotations

from umcp_core.core import DomainTag, TaskStatus
from escort_driving.tasks import EscortTask


class TestEscortTask:
    def test_create_with_location_and_skills(self):
        task = EscortTask(
            demander_id="u_student_1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            car_type="manual",
            required_skills=["highway", "night"],
            duration_hours=2.0,
        )
        assert task.spatio_temporal is not None
        assert task.spatio_temporal.origin_lat == 39.9042
        assert task.spatio_temporal.origin_lng == 116.4074
        assert task.structured_fields["car_type"] == "manual"
        assert task.structured_fields["required_skills"] == ["highway", "night"]
        assert task.structured_fields["duration_hours"] == 2.0

    def test_default_car_type_is_manual(self):
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
        )
        assert task.structured_fields["car_type"] == "manual"

    def test_default_required_skills_is_empty_list(self):
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
        )
        assert task.structured_fields["required_skills"] == []

    def test_default_duration_is_one_hour(self):
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
        )
        assert task.structured_fields["duration_hours"] == 1.0

    def test_has_actual_hours_for_hourly_pricing(self):
        """EscortTask 应包含 actual_hours 字段供 Hourly 策略计算。"""
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            duration_hours=2.5,
        )
        # 默认 actual_hours 等于 duration_hours
        assert task.custom_fields["actual_hours"] == 2.5

    def test_task_type_is_escort(self):
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
        )
        assert task.task_type() == "escort"

    def test_task_type_name_attribute_for_factory_registration(self):
        """_task_type_name 属性供 UMCPServer._apply_manifest 注册到 TaskFactory。"""
        assert EscortTask._task_type_name == "escort"

    def test_publish_transitions_to_matching(self):
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
        )
        task.publish()
        assert task.status == TaskStatus.MATCHING

    def test_custom_car_type_automatic(self):
        task = EscortTask(
            demander_id="u1",
            domain_tag=DomainTag.of("escort"),
            origin_lat=39.9,
            origin_lng=116.4,
            car_type="automatic",
        )
        assert task.structured_fields["car_type"] == "automatic"
