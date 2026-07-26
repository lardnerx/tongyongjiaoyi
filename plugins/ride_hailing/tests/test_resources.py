"""测试 DriverResource。"""

from __future__ import annotations

from umcp_core.core import Capability, DomainTag, ResourceStatus
from ride_hailing.resources import DriverResource


class TestDriverResource:
    def test_create_driver_with_location(self):
        driver = DriverResource(
            supplier_id="u_driver_1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.91,
            current_lng=116.41,
        )
        assert driver.metadata["current_lat"] == 39.91
        assert driver.metadata["current_lng"] == 116.41

    def test_default_car_type_is_economy(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.metadata["car_type"] == "economy"

    def test_custom_car_type(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
            car_type="comfort",
        )
        assert driver.metadata["car_type"] == "comfort"

    def test_has_plate_number(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
            plate_number="京A12345",
        )
        assert driver.metadata["plate_number"] == "京A12345"

    def test_default_has_driver_license_capability(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.has_capability("driver_license")

    def test_custom_capabilities_override_default(self):
        extra = [
            Capability(type="certification", name="driver_license", value="C1", verified=True),
            Capability(type="certification", name="vehicle_license", verified=True),
        ]
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
            capabilities=extra,
        )
        assert driver.has_capability("driver_license")
        assert driver.has_capability("vehicle_license")

    def test_register_sets_idle(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.status == ResourceStatus.OFFLINE
        driver.register()
        assert driver.status == ResourceStatus.IDLE
        assert driver.is_available()

    def test_resource_type_is_driver(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.resource_type() == "driver"
