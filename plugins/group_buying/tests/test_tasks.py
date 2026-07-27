"""BuyerTask 测试。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import TaskStatus
from group_buying.tasks import BuyerTask


def test_buyer_task_basic_fields():
    """BuyerTask 字段正确设置。"""
    task = BuyerTask(
        demander_id="buyer_001",
        domain_tag=DomainTag.of("group_buying"),
        category="空调",
        quantity=10,
        budget_max=3000.0,
        spec_requirements=["1.5匹", "变频"],
    )
    assert task.demander_id == "buyer_001"
    assert task.task_type() == "buyer"
    assert task._task_type_name == "buyer"
    assert task.status == TaskStatus.DRAFT
    assert task.custom_fields["category"] == "空调"
    assert task.custom_fields["quantity"] == 10
    assert task.custom_fields["spec_requirements"] == ["1.5匹", "变频"]


def test_buyer_task_budget_inherited_from_custom_task():
    """预算字段继承自 CustomTask。"""
    task = BuyerTask(
        demander_id="buyer_001",
        domain_tag=DomainTag.of("group_buying"),
        category="空调",
        quantity=10,
        budget_max=3000.0,
    )
    assert task.budget_max == 3000.0
    assert task.budget_min is None  # 默认无下限


def test_buyer_task_spec_requirements_default_empty():
    """spec_requirements 默认为空列表。"""
    task = BuyerTask(
        demander_id="buyer_001",
        domain_tag=DomainTag.of("group_buying"),
        category="保洁",
        quantity=1,
        budget_max=500.0,
    )
    assert task.custom_fields["spec_requirements"] == []


def test_buyer_task_publish_transitions_to_matching():
    """发布后进入 MATCHING 状态。"""
    task = BuyerTask(
        demander_id="buyer_001",
        domain_tag=DomainTag.of("group_buying"),
        category="空调",
        quantity=10,
        budget_max=3000.0,
    )
    task.publish()
    assert task.status == TaskStatus.MATCHING
