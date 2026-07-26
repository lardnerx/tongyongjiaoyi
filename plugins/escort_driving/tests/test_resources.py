"""测试 CoachResource。"""

from __future__ import annotations

from umcp_core.core import DomainTag, ResourceStatus
from escort_driving.resources import CoachResource


class TestCoachResource:
    def test_create_coach_with_location_and_skills(self):
        coach = CoachResource(
            supplier_id="s_coach_1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.905,
            current_lng=116.408,
            car_type="manual",
            coach_level="A",
            skills=["highway", "night", "parking"],
            plate_number="京B88888",
        )
        assert coach.metadata["current_lat"] == 39.905
        assert coach.metadata["current_lng"] == 116.408
        assert coach.metadata["car_type"] == "manual"
        assert coach.metadata["coach_level"] == "A"
        assert coach.metadata["skills"] == ["highway", "night", "parking"]
        assert coach.metadata["plate_number"] == "京B88888"

    def test_default_car_type_is_manual(self):
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert coach.metadata["car_type"] == "manual"

    def test_default_coach_level_is_b(self):
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert coach.metadata["coach_level"] == "B"

    def test_default_skills_is_empty_list(self):
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert coach.metadata["skills"] == []

    def test_default_has_coach_license_capability(self):
        """默认应具备 coach_license 能力（准入规则要求）。"""
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert coach.has_capability("coach_license")

    def test_custom_capabilities_override_default(self):
        """显式传入 capabilities 时应覆盖默认。"""
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.9,
            current_lng=116.4,
            capabilities=[],
        )
        assert not coach.has_capability("coach_license")

    def test_register_sets_idle(self):
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert coach.status == ResourceStatus.OFFLINE
        coach.register()
        assert coach.status == ResourceStatus.IDLE

    def test_resource_type_is_coach(self):
        coach = CoachResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("escort"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert coach.resource_type() == "coach"
