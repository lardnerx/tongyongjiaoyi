"""测试 L3 匹配策略与预过滤器。"""

from __future__ import annotations

import pytest

from umcp_core.core import Capability, DomainTag, Resource, ResourceStatus, StandardTask, TaskStatus
from umcp_core.layers.l3 import (
    Bidding,
    CapabilityFilter,
    CredentialFilter,
    DirectPick,
    InstantMatch,
    MatchResult,
    ProposalBid,
    ReverseAuction,
    TrustThresholdFilter,
)


class _RideTask(StandardTask):
    def task_type(self) -> str:
        return "ride"


class _DriverResource(Resource):
    def resource_type(self) -> str:
        return "driver"


def _make_driver(
    supplier_id: str,
    capabilities: list[Capability] | None = None,
    available: bool = True,
) -> _DriverResource:
    res = _DriverResource(
        supplier_id=supplier_id,
        domain_tag=DomainTag.of("ride"),
        capabilities=capabilities,
    )
    if available:
        res.register()
    return res


class TestPreMatchFilters:
    def test_credential_filter_pass(self):
        cap = Capability(type="certification", name="driver_license", verified=True)
        res = _make_driver("s1", capabilities=[cap])
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))

        f = CredentialFilter(required_credentials=["driver_license"])
        assert f.filter(task, res)

    def test_credential_filter_block(self):
        res = _make_driver("s1")
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))

        f = CredentialFilter(required_credentials=["driver_license"])
        assert not f.filter(task, res)

    def test_capability_filter(self):
        cap = Capability(type="skill", name="driving", verified=True)
        res = _make_driver("s1", capabilities=[cap])

        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.custom_fields["required_capabilities"] = ["driving"]
        assert CapabilityFilter().filter(task, res)

        task.custom_fields["required_capabilities"] = ["cooking"]
        assert not CapabilityFilter().filter(task, res)

    def test_trust_threshold_filter(self):
        res = _make_driver("s1")
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))

        f = TrustThresholdFilter(threshold=4.5, trust_lookup=lambda uid: 4.8)
        assert f.filter(task, res)

        f_low = TrustThresholdFilter(threshold=4.5, trust_lookup=lambda uid: 3.0)
        assert not f_low.filter(task, res)

    def test_trust_filter_without_lookup(self):
        res = _make_driver("s1")
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        f = TrustThresholdFilter(threshold=4.5)  # 无 lookup
        assert f.filter(task, res)


class TestInstantMatch:
    def test_match_returns_first_candidate(self):
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.publish()
        drivers = [_make_driver(f"s{i}") for i in range(3)]

        strategy = InstantMatch()
        result = strategy.execute(task, drivers)

        assert result.matched
        assert result.selected_resource_id is not None
        assert len(result.candidates) == 3

    def test_match_with_filters(self):
        cap = Capability(type="certification", name="driver_license", verified=True)
        licensed = _make_driver("s1", capabilities=[cap])
        unlicensed = _make_driver("s2")

        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.publish()

        strategy = InstantMatch(filters=[CredentialFilter(["driver_license"])])
        result = strategy.execute(task, [licensed, unlicensed])

        assert result.matched
        assert result.selected_resource_id == licensed.resource_id
        assert len(result.candidates) == 1

    def test_no_candidates_returns_unmatched(self):
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.publish()
        strategy = InstantMatch()
        result = strategy.execute(task, [])
        assert not result.matched


class TestDirectPick:
    def test_returns_all_candidates_without_selection(self):
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.publish()
        drivers = [_make_driver(f"s{i}") for i in range(3)]

        result = DirectPick().execute(task, drivers)
        assert not result.matched
        assert len(result.candidates) == 3


class TestBidding:
    def test_reverse_auction_returns_candidates(self):
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.publish()
        drivers = [_make_driver(f"s{i}") for i in range(3)]

        result = ReverseAuction().execute(task, drivers)
        assert not result.matched
        assert result.metadata["mode"] == "reverse_auction"
        assert result.metadata["awaiting_proposals"]

    def test_proposal_bid_mode(self):
        task = _RideTask(demander_id="d1", domain_tag=DomainTag.of("ride"))
        result = ProposalBid().execute(task, [])
        assert result.metadata["mode"] == "proposal_bid"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="未知招标模式"):
            Bidding(mode="invalid")
