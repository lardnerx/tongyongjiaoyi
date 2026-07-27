"""CompositeBidScorer 通用报价评分器测试。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource
from umcp_core.core.task import Task
from umcp_core.layers.l3 import CompositeBidScorer


class _Task(Task):
    def task_type(self) -> str:
        return "test"


class _Resource(Resource):
    def resource_type(self) -> str:
        return "test"


def _make_resource(bid: dict, trust: float = 3.0) -> _Resource:
    r = _Resource(supplier_id="s1", domain_tag=DomainTag.of("test"))
    r.metadata["bid"] = bid
    r.metadata["trust_score"] = trust
    return r


def test_no_bid_data_returns_zero():
    """resource 无 bid metadata 时返回 0.0。"""
    scorer = CompositeBidScorer()
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    resource = _Resource(supplier_id="s1", domain_tag=DomainTag.of("test"))
    assert scorer(task, resource) == 0.0


def test_single_bid_neutral_full_score():
    """单 bid 场景无对比基准，价格分和交期分均为 1.0（中性满分）。"""
    scorer = CompositeBidScorer()
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    resource = _make_resource(bid={"price": 100.0, "delivery_days": 5}, trust=4.0)
    # 价格分 1.0 × 0.5 + 交期分 1.0 × 0.3 + 信誉分 4.0/5.0 × 0.2 = 0.5 + 0.3 + 0.16 = 0.96
    assert scorer(task, resource) == 0.96


def test_price_normalization_lower_price_higher_score():
    """价格越低分越高（多 bid 场景）。"""
    scorer = CompositeBidScorer(price_weight=1.0, delivery_weight=0.0, trust_weight=0.0)
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    # 两个 bid 价格范围 [100, 200]
    cheap = _make_resource(bid={"price": 100.0, "delivery_days": 5})
    expensive = _make_resource(bid={"price": 200.0, "delivery_days": 5})
    # 便宜者价格分 = (200-100)/(200-100) = 1.0
    # 昂贵者价格分 = (200-200)/(200-100) = 0.0
    # 但 scorer 只看单个 resource，需通过 task 携带对比基准
    task.custom_fields["bid_price_range"] = (100.0, 200.0)
    task.custom_fields["bid_delivery_range"] = (5, 5)
    assert scorer(task, cheap) == 1.0
    assert scorer(task, expensive) == 0.0


def test_delivery_normalization_shorter_delivery_higher_score():
    """交期越短分越高。"""
    scorer = CompositeBidScorer(price_weight=0.0, delivery_weight=1.0, trust_weight=0.0)
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    task.custom_fields["bid_price_range"] = (100.0, 100.0)
    task.custom_fields["bid_delivery_range"] = (3, 10)
    fast = _make_resource(bid={"price": 100.0, "delivery_days": 3})
    slow = _make_resource(bid={"price": 100.0, "delivery_days": 10})
    assert scorer(task, fast) == 1.0
    assert scorer(task, slow) == 0.0


def test_trust_score_component():
    """信誉分 = trust_score / 5.0。"""
    scorer = CompositeBidScorer(price_weight=0.0, delivery_weight=0.0, trust_weight=1.0)
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    task.custom_fields["bid_price_range"] = (100.0, 100.0)
    task.custom_fields["bid_delivery_range"] = (5, 5)
    high_trust = _make_resource(bid={"price": 100.0, "delivery_days": 5}, trust=5.0)
    low_trust = _make_resource(bid={"price": 100.0, "delivery_days": 5}, trust=2.0)
    assert scorer(task, high_trust) == 1.0
    assert scorer(task, low_trust) == 0.4


def test_weighted_sum():
    """综合分 = 价格分×pw + 交期分×dw + 信誉分×tw。"""
    scorer = CompositeBidScorer(price_weight=0.5, delivery_weight=0.3, trust_weight=0.2)
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    task.custom_fields["bid_price_range"] = (100.0, 200.0)
    task.custom_fields["bid_delivery_range"] = (3, 10)
    # 价格分=1.0, 交期分=1.0, 信誉分=4.0/5.0=0.8
    resource = _make_resource(bid={"price": 100.0, "delivery_days": 3}, trust=4.0)
    expected = 1.0 * 0.5 + 1.0 * 0.3 + 0.8 * 0.2
    assert scorer(task, resource) == round(expected, 6)


def test_higher_score_is_better():
    """高分优先方向：综合分越高代表越优报价（配合 reverse=True）。"""
    scorer = CompositeBidScorer()
    task = _Task(demander_id="u1", domain_tag=DomainTag.of("test"))
    task.custom_fields["bid_price_range"] = (100.0, 200.0)
    task.custom_fields["bid_delivery_range"] = (3, 10)
    best = _make_resource(bid={"price": 100.0, "delivery_days": 3}, trust=5.0)
    worst = _make_resource(bid={"price": 200.0, "delivery_days": 10}, trust=2.0)
    assert scorer(task, best) > scorer(task, worst)
