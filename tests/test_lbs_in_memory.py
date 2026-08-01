"""LBS 内存实现测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def lbs():
    from umcp_core.shared.lbs.in_memory import InMemoryLBSService
    return InMemoryLBSService()


def test_lbs_update_location_stores_latest(lbs):
    lbs.update_location("res_1", lat=39.9042, lng=116.4074, heading=90.0, speed=30.0)
    loc = lbs.get_location("res_1")
    assert loc is not None
    assert loc["lat"] == 39.9042
    assert loc["lng"] == 116.4074
    assert loc["heading"] == 90.0


def test_lbs_nearby_returns_sorted_by_distance(lbs):
    lbs.update_location("res_1", lat=39.9042, lng=116.4074)
    lbs.update_location("res_2", lat=39.9050, lng=116.4080)  # 更近
    lbs.update_location("res_3", lat=40.0000, lng=117.0000)  # 很远
    result = lbs.nearby(lat=39.9042, lng=116.4074, radius_km=10.0)
    resource_ids = [r["resource_id"] for r in result]
    assert "res_1" in resource_ids
    assert "res_2" in resource_ids
    assert "res_3" not in resource_ids
    # 距离升序
    assert result[0]["distance_km"] <= result[1]["distance_km"]


def test_lbs_nearby_respects_radius(lbs):
    lbs.update_location("res_1", lat=39.9042, lng=116.4074)
    lbs.update_location("res_2", lat=40.0000, lng=117.0000)
    result = lbs.nearby(lat=39.9042, lng=116.4074, radius_km=1.0)
    assert len(result) == 1
    assert result[0]["resource_id"] == "res_1"


def test_lbs_distance_returns_meters(lbs):
    d = lbs.distance(39.9042, 116.4074, 39.9050, 116.4080)
    assert d > 0
    assert d < 1.0  # 很近的两个点


def test_lbs_get_location_returns_none_when_absent(lbs):
    assert lbs.get_location("nonexistent") is None
