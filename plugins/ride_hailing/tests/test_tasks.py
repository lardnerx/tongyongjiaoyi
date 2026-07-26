"""测试 RideTask。"""

from __future__ import annotations

import pytest

from umcp_core.core import DomainTag, TaskStatus
from umcp_core.core.domain import SpatioTemporalConstraint
from ride_hailing.tasks import RideTask


class TestRideTask:
    def test_create_with_origin_and_destination(self):
        task = RideTask(
            demander_id="u_passenger_1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        assert task.spatio_temporal is not None
        assert task.spatio_temporal.origin_lat == 39.9042
        assert task.spatio_temporal.origin_lng == 116.4074
        assert task.spatio_temporal.dest_lat == 39.9590
        assert task.spatio_temporal.dest_lng == 116.4518

    def test_default_car_type_is_economy(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.structured_fields["car_type"] == "economy"

    def test_custom_car_type(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
            car_type="comfort",
        )
        assert task.structured_fields["car_type"] == "comfort"

    def test_default_passenger_count_is_one(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.structured_fields["passenger_count"] == 1

    def test_has_base_price_for_dynamic_pricing(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.custom_fields["base_price"] > 0

    def test_task_type_is_ride(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.task_type() == "ride"

    def test_task_type_name_attribute_for_factory_registration(self):
        """_task_type_name 属性供 UMCPServer._apply_manifest 注册到 TaskFactory。"""
        assert RideTask._task_type_name == "ride"

    def test_publish_transitions_to_matching(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        task.publish()
        assert task.status == TaskStatus.MATCHING

    def test_estimated_distance_calculated(self):
        """行程预估距离应基于起终点自动计算。"""
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,  # 北京天安门
            origin_lng=116.4074,
            dest_lat=39.9590,    # 北京鸟巢
            dest_lng=116.4518,
        )
        # 天安门到鸟巢约 7-8 公里
        assert 5.0 < task.structured_fields["estimated_distance_km"] < 10.0
