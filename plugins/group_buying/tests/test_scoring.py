"""TenderBidScorer 测试。"""
from __future__ import annotations

import pytest

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability
from umcp_core.core.task import Task
from group_buying.resources import SupplierResource
from group_buying.scoring import TenderBidScorer, MISSING_REQUIREMENT_SCORE


class _Task(Task):
    def task_type(self) -> str:
        return "test"


def _make_task_with_bid_range(price_range=(100.0, 200.0), delivery_range=(3, 10), required_tags=None):
    task = _Task(demander_id="broker_001", domain_tag=DomainTag.of("group_buying"))
    task.custom_fields["bid_price_range"] = price_range
    task.custom_fields["bid_delivery_range"] = delivery_range
    if required_tags:
        task.custom_fields["required_service_tags"] = required_tags
    return task


def _make_supplier_with_bid(price, delivery_days, trust=4.0, service_tags=None, has_license=True):
    caps = None if has_license else []
    supplier = SupplierResource(
        supplier_id="s1",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="供应商",
        product_sku="SKU",
        service_capability=service_tags or [],
        trust_score=trust,
        capabilities=caps,
    )
    supplier.metadata["bid"] = {"price": price, "delivery_days": delivery_days}
    return supplier


def test_no_business_license_returns_mismatch_score():
    """无 business_license 直接返回 -1.0。"""
    scorer = TenderBidScorer()
    task = _make_task_with_bid_range()
    supplier = _make_supplier_with_bid(price=100.0, delivery_days=3, has_license=False)
    assert scorer(task, supplier) == MISSING_REQUIREMENT_SCORE


def test_service_tag_mismatch_returns_mismatch_score():
    """服务标签不匹配返回 -1.0。"""
    scorer = TenderBidScorer(required_service_tags=["delivery", "installation"])
    task = _make_task_with_bid_range()
    task.custom_fields["required_service_tags"] = ["delivery", "installation"]
    supplier = _make_supplier_with_bid(
        price=100.0, delivery_days=3, service_tags=["delivery"]  # 缺 installation
    )
    assert scorer(task, supplier) == MISSING_REQUIREMENT_SCORE


def test_all_requirements_met_returns_composite_score():
    """资质+服务标签都满足时返回 CompositeBidScorer 评分。"""
    scorer = TenderBidScorer(required_service_tags=["delivery", "installation"])
    task = _make_task_with_bid_range()
    task.custom_fields["required_service_tags"] = ["delivery", "installation"]
    supplier = _make_supplier_with_bid(
        price=100.0, delivery_days=3, trust=5.0,
        service_tags=["delivery", "installation"],
    )
    # 价格分=1.0, 交期分=1.0, 信誉分=5.0/5.0=1.0
    # 综合 = 1.0*0.5 + 1.0*0.3 + 1.0*0.2 = 1.0
    assert scorer(task, supplier) == 1.0


def test_lower_price_higher_score():
    """价格越低分越高。"""
    scorer = TenderBidScorer()
    task = _make_task_with_bid_range(price_range=(100.0, 200.0))
    cheap = _make_supplier_with_bid(price=100.0, delivery_days=5, trust=3.0)
    expensive = _make_supplier_with_bid(price=200.0, delivery_days=5, trust=3.0)
    assert scorer(task, cheap) > scorer(task, expensive)


def test_shorter_delivery_higher_score():
    """交期越短分越高。"""
    scorer = TenderBidScorer()
    task = _make_task_with_bid_range(delivery_range=(3, 10))
    fast = _make_supplier_with_bid(price=100.0, delivery_days=3, trust=3.0)
    slow = _make_supplier_with_bid(price=100.0, delivery_days=10, trust=3.0)
    assert scorer(task, fast) > scorer(task, slow)


def test_higher_trust_higher_score():
    """信誉越高分越高。"""
    scorer = TenderBidScorer()
    task = _make_task_with_bid_range()
    high_trust = _make_supplier_with_bid(price=100.0, delivery_days=5, trust=5.0)
    low_trust = _make_supplier_with_bid(price=100.0, delivery_days=5, trust=2.0)
    assert scorer(task, high_trust) > scorer(task, low_trust)


def test_no_required_service_tags_skips_tag_check():
    """未配置 required_service_tags 时跳过标签检查。"""
    scorer = TenderBidScorer(required_service_tags=None)
    task = _make_task_with_bid_range()
    supplier = _make_supplier_with_bid(
        price=100.0, delivery_days=3, trust=4.0, service_tags=[],  # 无任何服务标签
    )
    # 资质通过 + 无标签要求 → 走 CompositeBidScorer
    assert scorer(task, supplier) > 0.0


def test_composite_weights_applied():
    """组合权重正确应用（价格0.5 + 交期0.3 + 信誉0.2）。"""
    scorer = TenderBidScorer()
    task = _make_task_with_bid_range(price_range=(100.0, 200.0), delivery_range=(3, 10))
    supplier = _make_supplier_with_bid(
        price=100.0, delivery_days=3, trust=4.0,  # 价格分1.0, 交期分1.0, 信誉分0.8
    )
    expected = 1.0 * 0.5 + 1.0 * 0.3 + 0.8 * 0.2
    assert scorer(task, supplier) == round(expected, 6)
