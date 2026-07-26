"""测试距离计算与匹配评分器。"""

from __future__ import annotations

import pytest

from umcp_core.core import DomainTag
from ride_hailing.resources import DriverResource
from ride_hailing.scoring import RideMatchScorer, haversine_km
from ride_hailing.tasks import RideTask


class TestHaversine:
    def test_same_point_returns_zero(self):
        assert haversine_km(39.9, 116.4, 39.9, 116.4) == 0.0

    def test_beijing_tiananmen_to_birds_nest(self):
        """天安门到鸟巢约 7-8 公里。"""
        dist = haversine_km(39.9042, 116.4074, 39.9590, 116.4518)
        assert 5.0 < dist < 10.0

    def test_distance_is_symmetric(self):
        d1 = haversine_km(39.9, 116.4, 39.95, 116.45)
        d2 = haversine_km(39.95, 116.45, 39.9, 116.4)
        assert abs(d1 - d2) < 0.001

    def test_distance_positive(self):
        assert haversine_km(39.9, 116.4, 40.0, 116.5) > 0


class TestRideMatchScorer:
    def test_closer_driver_scores_higher(self):
        """距离近的司机评分应更高（返回负距离，近者绝对值小，升序排在前）。"""
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        close_driver = DriverResource(
            supplier_id="s_close",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,   # 非常近
            current_lng=116.408,
        )
        far_driver = DriverResource(
            supplier_id="s_far",
            domain_tag=DomainTag.of("ride"),
            current_lat=40.0,      # 较远
            current_lng=116.5,
        )
        scorer = RideMatchScorer()
        close_score = scorer(task, close_driver)
        far_score = scorer(task, far_driver)
        # 评分是负距离，近者评分更高（更接近 0）
        assert close_score > far_score

    def test_returns_zero_when_task_has_no_location(self):
        """任务无时空约束时返回 0（中性评分）。"""
        from umcp_core.core import StandardTask

        class _NoLocTask(StandardTask):
            def task_type(self) -> str:
                return "test"

        task = _NoLocTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        driver = DriverResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        scorer = RideMatchScorer()
        assert scorer(task, driver) == 0.0

    def test_returns_zero_when_driver_has_no_location(self):
        """司机无位置元数据时返回 0。"""
        from umcp_core.core import DomainTag, Resource

        class _NoLocDriver(Resource):
            def resource_type(self) -> str:
                return "driver"

        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        driver = _NoLocDriver(supplier_id="s1", domain_tag=DomainTag.of("ride"))
        scorer = RideMatchScorer()
        assert scorer(task, driver) == 0.0
