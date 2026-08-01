"""ScheduledMatchStrategy 预约单 Top3 推荐测试。"""
from __future__ import annotations

from datetime import datetime

import pytest


def _make_coach(resource_id: str, car_type: str = "AUTO", coach_level: str = "BRONZE"):
    """构造教练 Resource。"""
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus

    class _Coach(Resource):
        def __init__(self):
            super().__init__(
                supplier_id="supplier_1",
                domain_tag=DomainTag.of("escort"),
                resource_id=resource_id,
            )
            self.status = ResourceStatus.IDLE

        def resource_type(self) -> str:
            return "coach"

    coach = _Coach()
    coach.metadata["car_type"] = car_type
    coach.metadata["coach_level"] = coach_level
    return coach


def _make_scheduled_task(coach_level_pref: str = "ANY", car_type: str = "AUTO"):
    from plugins.escort_driving.tasks import EscortTask
    return EscortTask(
        demander_id="student_1",
        origin_lat=39.9042,
        origin_lng=116.4074,
        car_type=car_type,
        required_skills=["escort"],
        duration_hours=2,
        order_type="SCHEDULED",
        scheduled_at=datetime(2026, 8, 15, 10, 0),
        coach_level_pref=coach_level_pref,
    )


def test_scheduled_match_returns_top3_sorted_by_score():
    from plugins.escort_driving.scheduled_match import ScheduledMatchStrategy
    strategy = ScheduledMatchStrategy(top_n=3)
    task = _make_scheduled_task()
    candidates = [
        _make_coach("coach_1", car_type="AUTO"),
        _make_coach("coach_2", car_type="AUTO"),
        _make_coach("coach_3", car_type="AUTO"),
        _make_coach("coach_4", car_type="AUTO"),
    ]
    result = strategy.execute(task, candidates)
    assert result.task_id == task.task_id
    assert result.selected_resource_id is None  # 预约单不自动选定
    assert len(result.candidates) <= 3


def test_scheduled_match_filters_car_type_mismatch():
    from plugins.escort_driving.scheduled_match import ScheduledMatchStrategy
    strategy = ScheduledMatchStrategy(top_n=3)
    task = _make_scheduled_task(car_type="MANUAL")
    candidates = [
        _make_coach("coach_1", car_type="AUTO"),  # 不匹配
        _make_coach("coach_2", car_type="MANUAL"),  # 匹配
    ]
    result = strategy.execute(task, candidates)
    assert "coach_2" in result.candidates
    assert "coach_1" not in result.candidates


def test_scheduled_match_filters_coach_level_when_specified():
    from plugins.escort_driving.scheduled_match import ScheduledMatchStrategy
    strategy = ScheduledMatchStrategy(top_n=3)
    task = _make_scheduled_task(coach_level_pref="SILVER")
    candidates = [
        _make_coach("coach_1", coach_level="BRONZE"),  # 不匹配
        _make_coach("coach_2", coach_level="SILVER"),  # 匹配
        _make_coach("coach_3", coach_level="GOLD"),  # 不匹配
    ]
    result = strategy.execute(task, candidates)
    assert "coach_2" in result.candidates
    assert "coach_1" not in result.candidates
    assert "coach_3" not in result.candidates


def test_scheduled_match_any_level_includes_all_car_matches():
    from plugins.escort_driving.scheduled_match import ScheduledMatchStrategy
    strategy = ScheduledMatchStrategy(top_n=3)
    task = _make_scheduled_task(coach_level_pref="ANY")
    candidates = [
        _make_coach("coach_1", coach_level="BRONZE"),
        _make_coach("coach_2", coach_level="SILVER"),
        _make_coach("coach_3", coach_level="GOLD"),
    ]
    result = strategy.execute(task, candidates)
    assert len(result.candidates) == 3


def test_scheduled_match_top_n_limits_candidates():
    from plugins.escort_driving.scheduled_match import ScheduledMatchStrategy
    strategy = ScheduledMatchStrategy(top_n=2)
    task = _make_scheduled_task()
    candidates = [_make_coach(f"coach_{i}") for i in range(5)]
    result = strategy.execute(task, candidates)
    assert len(result.candidates) == 2
