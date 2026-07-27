"""BuyerTask 测试。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.task import CustomTask, StandardTask, TaskStatus
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


# ==================== TenderTask 测试 ====================
from group_buying.tasks import TenderTask


def _make_tender_with_subtasks(
    product_completed: bool = False,
    service_completed: bool = False,
) -> TenderTask:
    """创建带子任务的 TenderTask，子任务状态可控。"""
    product_sub = StandardTask(
        demander_id="broker_001",
        domain_tag=DomainTag.of("group_buying"),
    )
    product_sub.custom_fields["sku"] = "AC-1.5P"
    product_sub.custom_fields["quantity"] = 50
    if product_completed:
        product_sub.publish()
        product_sub.assign_to("res_1")
        product_sub.start_execution()
        product_sub.complete()

    service_sub = CustomTask(
        demander_id="broker_001",
        domain_tag=DomainTag.of("group_buying"),
    )
    service_sub.proposal_requirements = ["含安装", "含调试"]
    if service_completed:
        service_sub.publish()
        service_sub.assign_to("res_1")
        service_sub.start_execution()
        service_sub.complete()

    tender = TenderTask(
        demander_id="broker_001",
        domain_tag=DomainTag.of("group_buying"),
        category="空调",
        total_quantity=50,
        target_unit_price=2800.0,
        buyer_task_ids=["buyer_1", "buyer_2", "buyer_3"],
        standard_sub_tasks=[product_sub],
        custom_sub_task=service_sub,
    )
    return tender


def test_tender_task_basic_fields():
    """TenderTask 字段正确设置。"""
    tender = _make_tender_with_subtasks()
    assert tender.demander_id == "broker_001"
    assert tender.task_type() == "tender"
    assert tender._task_type_name == "tender"
    assert tender.custom_fields["category"] == "空调"
    assert tender.custom_fields["total_quantity"] == 50
    assert tender.custom_fields["target_unit_price"] == 2800.0
    assert tender.custom_fields["buyer_task_ids"] == ["buyer_1", "buyer_2", "buyer_3"]
    assert len(tender.standard_sub_tasks) == 1
    assert tender.custom_sub_task is not None


def test_tender_task_complete_raises_if_subtasks_not_done():
    """子任务未完成时 complete() 抛 RuntimeError。"""
    tender = _make_tender_with_subtasks(product_completed=False, service_completed=False)
    tender.publish()  # DRAFT → MATCHING
    tender.assign_to("res_1")  # MATCHING → ASSIGNED
    tender.start_execution()  # ASSIGNED → IN_PROGRESS
    import pytest
    with pytest.raises(RuntimeError, match="子任务"):
        tender.complete()


def test_tender_task_complete_raises_if_only_product_done():
    """仅商品子任务完成时 complete() 抛 RuntimeError。"""
    tender = _make_tender_with_subtasks(product_completed=True, service_completed=False)
    tender.publish()
    tender.assign_to("res_1")
    tender.start_execution()
    import pytest
    with pytest.raises(RuntimeError, match="服务子任务"):
        tender.complete()


def test_tender_task_complete_succeeds_when_all_subtasks_done():
    """所有子任务完成后 complete() 成功。"""
    tender = _make_tender_with_subtasks(product_completed=True, service_completed=True)
    tender.publish()
    tender.assign_to("res_1")
    tender.start_execution()
    tender.complete()
    from umcp_core.core.task import TaskStatus
    assert tender.status == TaskStatus.COMPLETED


def test_tender_task_complete_raises_if_only_service_done():
    """仅服务子任务完成时 complete() 抛 RuntimeError。"""
    tender = _make_tender_with_subtasks(product_completed=False, service_completed=True)
    tender.publish()
    tender.assign_to("res_1")
    tender.start_execution()
    import pytest
    with pytest.raises(RuntimeError, match="子任务"):
        tender.complete()
