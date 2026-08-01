"""EscortTask 扩展字段测试。"""
from __future__ import annotations

from datetime import datetime

import pytest


def test_escort_task_supports_realtime_order():
    from plugins.escort_driving.tasks import EscortTask
    task = EscortTask(
        demander_id="student_1",
        origin_lat=39.9042,
        origin_lng=116.4074,
        car_type="AUTO",
        required_skills=["escort"],
        duration_hours=2,
        order_type="REALTIME",
    )
    assert task.order_type == "REALTIME"
    assert task.scheduled_at is None
    assert task.coach_level_pref == "ANY"


def test_escort_task_supports_scheduled_order():
    from plugins.escort_driving.tasks import EscortTask
    scheduled = datetime(2026, 8, 15, 10, 0)
    task = EscortTask(
        demander_id="student_1",
        origin_lat=39.9042,
        origin_lng=116.4074,
        car_type="AUTO",
        required_skills=["escort"],
        duration_hours=2,
        order_type="SCHEDULED",
        scheduled_at=scheduled,
        coach_level_pref="SILVER",
    )
    assert task.order_type == "SCHEDULED"
    assert task.scheduled_at == scheduled
    assert task.coach_level_pref == "SILVER"


def test_escort_task_defaults_to_realtime():
    from plugins.escort_driving.tasks import EscortTask
    task = EscortTask(
        demander_id="student_1",
        origin_lat=39.9042,
        origin_lng=116.4074,
        car_type="AUTO",
        required_skills=["escort"],
        duration_hours=2,
    )
    assert task.order_type == "REALTIME"


def test_escort_task_structured_fields_include_extension():
    from plugins.escort_driving.tasks import EscortTask
    task = EscortTask(
        demander_id="student_1",
        origin_lat=39.9042,
        origin_lng=116.4074,
        car_type="AUTO",
        required_skills=["escort"],
        duration_hours=2,
        order_type="SCHEDULED",
        coach_level_pref="GOLD",
    )
    fields = task.structured_fields
    assert fields["order_type"] == "SCHEDULED"
    assert fields["coach_level_pref"] == "GOLD"
