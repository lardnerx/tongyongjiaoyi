"""SupplierResource 测试。"""
from __future__ import annotations

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, ResourceStatus
from group_buying.resources import SupplierResource


def test_supplier_resource_basic_fields():
    """SupplierResource 字段正确设置。"""
    supplier = SupplierResource(
        supplier_id="supplier_001",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="格力北京分公司",
        product_sku="AC-1.5P-GREE",
        service_capability=["delivery", "installation"],
        trust_score=4.5,
    )
    assert supplier.supplier_id == "supplier_001"
    assert supplier.resource_type() == "supplier"
    assert supplier.metadata["supplier_name"] == "格力北京分公司"
    assert supplier.metadata["product_sku"] == "AC-1.5P-GREE"
    assert supplier.metadata["service_capability"] == ["delivery", "installation"]
    assert supplier.metadata["trust_score"] == 4.5


def test_supplier_resource_default_business_license():
    """默认具备 business_license 能力（准入规则要求）。"""
    supplier = SupplierResource(
        supplier_id="supplier_001",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="供应商A",
        product_sku="SKU-001",
        service_capability=["delivery"],
    )
    assert supplier.has_capability("business_license")
    cap = next(c for c in supplier.capabilities if c.name == "business_license")
    assert cap.type == "certification"
    assert cap.verified is True


def test_supplier_resource_custom_capabilities_override_default():
    """自定义 capabilities 覆盖默认值。"""
    custom_caps = [
        Capability(type="certification", name="iso9001", value="certified", verified=True),
    ]
    supplier = SupplierResource(
        supplier_id="supplier_001",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="供应商B",
        product_sku="SKU-002",
        service_capability=["delivery"],
        capabilities=custom_caps,
    )
    assert not supplier.has_capability("business_license")
    assert supplier.has_capability("iso9001")


def test_supplier_resource_default_trust_score():
    """默认 trust_score 为 3.0。"""
    supplier = SupplierResource(
        supplier_id="supplier_001",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="供应商C",
        product_sku="SKU-003",
        service_capability=["delivery"],
    )
    assert supplier.metadata["trust_score"] == 3.0


def test_supplier_resource_default_status_offline():
    """默认状态为 OFFLINE。"""
    supplier = SupplierResource(
        supplier_id="supplier_001",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="供应商D",
        product_sku="SKU-004",
        service_capability=["delivery"],
    )
    assert supplier.status == ResourceStatus.OFFLINE


def test_supplier_resource_register_transitions_to_idle():
    """register() 后状态为 IDLE。"""
    supplier = SupplierResource(
        supplier_id="supplier_001",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="供应商E",
        product_sku="SKU-005",
        service_capability=["delivery"],
    )
    supplier.register()
    assert supplier.status == ResourceStatus.IDLE


def test_supplier_resource_empty_service_capability():
    """service_capability 默认为空列表。"""
    supplier = SupplierResource(
        supplier_id="supplier_001",
        domain_tag=DomainTag.of("group_buying"),
        supplier_name="供应商F",
        product_sku="SKU-006",
        service_capability=None,
    )
    assert supplier.metadata["service_capability"] == []
