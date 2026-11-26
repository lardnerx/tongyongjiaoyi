"""领域对象 ↔ ORM 模型转换器（纯函数）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.core.deal import Deal
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource
from umcp_core.core.task import CustomTask, PackageTask, StandardTask, Task, TaskStatus
from umcp_core.core.composite_task import CompositeTask
from umcp_core.events.bus import Event
from umcp_core.layers.l5 import Evaluation, TrustProfile
from umcp_core.repositories.postgres.models import (
    CompositeDependencyModel,
    DealModel,
    EventModel,
    ResourceModel,
    TaskModel,
    TrustEvaluationModel,
    TrustProfileModel,
    UserModel,
)

# task_type → 领域类的映射
_TASK_TYPE_REGISTRY: dict[str, type[Task]] = {
    "standard": StandardTask,
    "custom": CustomTask,
    "package": PackageTask,
    "composite": CompositeTask,
}

# TaskModel 没有结构化字段列，插件任务（如 escort）的 structured_fields
# 以该保留键随 custom_fields（JSONB）一起持久化，避免往返丢失
_STRUCTURED_FIELDS_KEY = "__structured_fields__"


# ------------------------------------------------------------------
# Task 转换器
# ------------------------------------------------------------------


def task_to_orm(task: Task) -> TaskModel:
    """领域 Task → ORM TaskModel。"""
    parent_task_id = getattr(task, "parent_task_id", None)
    custom_fields = dict(task.custom_fields)
    structured_fields = getattr(task, "structured_fields", None)
    if structured_fields:
        custom_fields[_STRUCTURED_FIELDS_KEY] = structured_fields
    return TaskModel(
        task_id=task.task_id,
        task_type=task.task_type(),
        demander_id=task.demander_id,
        domain_tag=task.domain_tag.value,
        title=task.title,
        description=task.description,
        status=task.status,
        supplier_id=getattr(task, "supplier_id", None),
        assigned_resource_id=task.assigned_resource_id,
        parent_task_id=parent_task_id,
        custom_fields=custom_fields,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def task_from_orm(model: TaskModel) -> Task:
    """ORM TaskModel → 领域 Task（按 task_type 重建对应子类）。

    注意：CompositeTask 的 dependencies 和 subtasks 需要额外查询重建，
    此函数只重建基本字段，使用 composite_task_from_orm 重建完整 CompositeTask。
    """
    cls = _TASK_TYPE_REGISTRY.get(model.task_type, StandardTask)
    task = cls(
        demander_id=model.demander_id,
        domain_tag=DomainTag.of(model.domain_tag),
        title=model.title or "",
        description=model.description or "",
    )
    task.task_id = model.task_id
    task.status = model.status
    task.assigned_resource_id = model.assigned_resource_id

    custom_fields = dict(model.custom_fields or {})
    structured_fields = custom_fields.pop(_STRUCTURED_FIELDS_KEY, None) or {}
    task.custom_fields = custom_fields
    if isinstance(task, StandardTask):
        task.structured_fields = structured_fields

    # 插件自定义任务在通用仓储中按 StandardTask 还原，补齐通用扩展属性，
    # 否则读取 order_type / scheduled_at 等字段会抛 AttributeError。
    # 插件专有字段统一保留在 structured_fields 中，由插件自行读取。
    if model.task_type not in _TASK_TYPE_REGISTRY:
        if structured_fields.get("order_type"):
            task.order_type = structured_fields["order_type"]
        if structured_fields.get("scheduled_at"):
            try:
                task.scheduled_at = datetime.fromisoformat(structured_fields["scheduled_at"])
            except (TypeError, ValueError):
                task.scheduled_at = None

    task.created_at = model.created_at
    task.updated_at = model.updated_at
    return task


def composite_task_from_orm(
    model: TaskModel,
    dependencies: dict[str, list[str]],
    subtasks: list[Task],
) -> CompositeTask:
    """重建 CompositeTask（含 dependencies 和 subtasks）。"""
    composite = task_from_orm(model)
    # 直接设置属性（CompositeTask 在 __init__ 后已校验过 DAG，
    # 恢复时跳过校验以接受已持久化的状态）
    composite.subtasks = subtasks
    composite.dependencies = dependencies
    return composite


# ------------------------------------------------------------------
# Resource 转换器
# ------------------------------------------------------------------


def _capability_to_dict(cap: Capability) -> dict[str, Any]:
    return {
        "type": cap.type,
        "name": cap.name,
        "value": cap.value,
        "verified": cap.verified,
        "expiry": cap.expiry.isoformat() if cap.expiry else None,
    }


def _capability_from_dict(data: dict[str, Any]) -> Capability:
    from datetime import datetime

    expiry = None
    if data.get("expiry"):
        expiry = datetime.fromisoformat(data["expiry"])
    return Capability(
        type=data["type"],
        name=data["name"],
        value=data.get("value", ""),
        verified=data.get("verified", False),
        expiry=expiry,
    )


def resource_to_orm(resource: Resource) -> ResourceModel:
    """领域 Resource → ORM ResourceModel。"""
    return ResourceModel(
        resource_id=resource.resource_id,
        supplier_id=resource.supplier_id,
        domain_tag=resource.domain_tag.value,
        resource_type=resource.resource_type(),
        status=resource.status,
        capabilities=[_capability_to_dict(c) for c in resource.capabilities],
        metadata_=resource.metadata,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


def resource_from_orm(model: ResourceModel) -> Resource:
    """ORM ResourceModel → 领域 Resource。

    注意：Resource 是抽象类，需要按 resource_type 重建子类。
    此函数创建一个通用 Resource 子类实例（用 _GenericResource 兜底）。
    """
    from umcp_core.core.resource import Resource as ResourceBase

    class _GenericResource(ResourceBase):
        def resource_type(self) -> str:
            return model.resource_type

    resource = _GenericResource(
        supplier_id=model.supplier_id,
        domain_tag=DomainTag.of(model.domain_tag),
        resource_id=model.resource_id,
        capabilities=[_capability_from_dict(c) for c in (model.capabilities or [])],
        metadata=model.metadata_ or {},
    )
    resource.status = model.status
    resource.created_at = model.created_at
    resource.updated_at = model.updated_at
    return resource


# ------------------------------------------------------------------
# Deal 转换器
# ------------------------------------------------------------------


def deal_to_orm(deal: Deal) -> DealModel:
    """领域 Deal → ORM DealModel。"""
    return DealModel(
        deal_id=deal.deal_id,
        task_id=deal.task_id,
        resource_id=deal.resource_id,
        supplier_id=deal.supplier_id,
        demander_id=deal.demander_id,
        final_amount=deal.final_amount,
        status=deal.status,
        completed_at=deal.completed_at,
        metadata_=deal.metadata,
        created_at=deal.matched_at,
        updated_at=deal.completed_at or deal.matched_at,
    )


def deal_from_orm(model: DealModel) -> Deal:
    """ORM DealModel → 领域 Deal。"""
    deal = Deal(
        task_id=model.task_id,
        resource_id=model.resource_id,
        demander_id=model.demander_id,
        supplier_id=model.supplier_id,
        deal_id=model.deal_id,
        final_amount=float(model.final_amount) if model.final_amount is not None else None,
        metadata=model.metadata_ or {},
    )
    deal.status = model.status
    deal.matched_at = model.created_at
    deal.completed_at = model.completed_at
    return deal


# ------------------------------------------------------------------
# User 转换器
# ------------------------------------------------------------------


def user_to_orm(user: Any) -> UserModel:
    """领域 User → ORM UserModel。

    注意：User 是抽象类，roles 和 active_role 序列化为 dict。
    """
    roles_data = {}
    for role_type, role in getattr(user, "roles", {}).items():
        perms = getattr(role, "permissions", None)
        perm_list = list(perms) if perms else []
        roles_data[role_type] = {"permissions": perm_list}

    return UserModel(
        user_id=user.user_id,
        name=user.name,
        user_type=user.active_role.role_type if getattr(user, "active_role", None) else "unknown",
        roles=roles_data,
        metadata_=getattr(user, "metadata", {}),
        # User 抽象基类没有 created_at/updated_at 字段，使用当前时间
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def user_from_orm(model: UserModel) -> Any:
    """ORM UserModel → 领域 User。

    注意：User 是抽象类，需要按 user_type 重建子类。
    此函数创建一个通用 User 子类实例。
    """
    from umcp_core.core.base import (
        Demander,
        PermissionSet,
        Role,
        Supplier,
        User as UserBase,
    )

    class _GenericUser(UserBase):
        def __init__(self, user_id: str, name: str, metadata: dict | None = None) -> None:
            super().__init__(user_id=user_id, name=name, metadata=metadata)

        def authenticate(self, credential: Any) -> bool:
            return True

    user = _GenericUser(
        user_id=model.user_id,
        name=model.name,
        metadata=model.metadata_ or {},
    )
    # 恢复 roles（roles 必须是 dict；脏数据按无角色处理，避免登录直接 500）
    roles_data = model.roles if isinstance(model.roles, dict) else {}
    for role_type, role_data in roles_data.items():
        data = role_data if isinstance(role_data, dict) else {}
        perms = PermissionSet(set(data.get("permissions", [])))
        if role_type == "demander":
            class _RestoredDemander(Demander):
                @property
                def permissions(self) -> PermissionSet:
                    return perms

            user.add_role(_RestoredDemander())
        elif role_type == "supplier":
            class _RestoredSupplier(Supplier):
                @property
                def permissions(self) -> PermissionSet:
                    return perms

            user.add_role(_RestoredSupplier())
        elif role_type == "admin":
            class _RestoredAdmin(Role):
                @property
                def role_type(self) -> str:
                    return "admin"

                @property
                def permissions(self) -> PermissionSet:
                    return perms

            user.add_role(_RestoredAdmin())
    return user


# ------------------------------------------------------------------
# TrustProfile 转换器
# ------------------------------------------------------------------


def trust_profile_to_orm(profile: TrustProfile) -> TrustProfileModel:
    """领域 TrustProfile → ORM TrustProfileModel。"""
    return TrustProfileModel(
        user_id=profile.user_id,
        domain_tag=profile.domain_tag,
        overall_score=profile.overall_score,
        dimension_scores=profile.dimension_scores,
        last_updated=profile.last_updated,
    )


def trust_profile_from_orm(model: TrustProfileModel) -> TrustProfile:
    """ORM TrustProfileModel → 领域 TrustProfile。"""
    return TrustProfile(
        user_id=model.user_id,
        dimension_scores=model.dimension_scores or {},
        overall_score=float(model.overall_score),
        last_updated=model.last_updated,
        domain_tag=model.domain_tag,
    )


# ------------------------------------------------------------------
# Evaluation 转换器
# ------------------------------------------------------------------


def evaluation_to_orm(evaluation: Evaluation) -> TrustEvaluationModel:
    """领域 Evaluation → ORM TrustEvaluationModel。"""
    return TrustEvaluationModel(
        evaluator_id=evaluation.evaluator_id,
        evaluatee_id=evaluation.evaluatee_id,
        task_id=evaluation.task_id,
        domain_tag=evaluation.domain_tag,
        ratings=evaluation.ratings,
        comment=evaluation.comment,
        created_at=evaluation.created_at,
    )


def evaluation_from_orm(model: TrustEvaluationModel) -> Evaluation:
    """ORM TrustEvaluationModel → 领域 Evaluation。"""
    return Evaluation(
        evaluator_id=model.evaluator_id,
        evaluatee_id=model.evaluatee_id,
        task_id=model.task_id,
        ratings=model.ratings or {},
        comment=model.comment or "",
        created_at=model.created_at,
        domain_tag=model.domain_tag,
    )


# ------------------------------------------------------------------
# Event 转换器
# ------------------------------------------------------------------


def event_to_orm(event: Event) -> EventModel:
    """领域 Event → ORM EventModel。"""
    return EventModel(
        event_type=event.type.value if hasattr(event.type, "value") else str(event.type),
        source_layer=event.source_layer,
        task_id=event.payload.get("task_id"),
        deal_id=event.payload.get("deal_id"),
        user_id=event.payload.get("user_id"),
        payload=event.payload,
        created_at=datetime.utcfromtimestamp(event.timestamp),
    )


def event_from_orm(model: EventModel) -> Event:
    """ORM EventModel → 领域 Event。"""
    from umcp_core.events.types import EventType

    event_type_str = model.event_type
    try:
        event_type = EventType(event_type_str)
    except ValueError:
        event_type = event_type_str  # 保留原始字符串

    return Event(
        type=event_type,
        source_layer=model.source_layer,
        payload=model.payload or {},
        timestamp=model.created_at.timestamp(),
    )


# ------------------------------------------------------------------
# CompositeDependency 转换器
# ------------------------------------------------------------------


def dependencies_to_orm(
    composite_task_id: str, dependencies: dict[str, list[str]]
) -> list[CompositeDependencyModel]:
    """依赖关系 dict → ORM CompositeDependencyModel 列表。"""
    models = []
    for subtask_id, deps in dependencies.items():
        for dep_id in deps:
            models.append(
                CompositeDependencyModel(
                    composite_task_id=composite_task_id,
                    subtask_id=subtask_id,
                    depends_on_id=dep_id,
                )
            )
    return models


def dependencies_from_orm(models: list[CompositeDependencyModel]) -> dict[str, list[str]]:
    """ORM CompositeDependencyModel 列表 → 依赖关系 dict。"""
    deps: dict[str, list[str]] = {}
    for model in models:
        deps.setdefault(model.subtask_id, []).append(model.depends_on_id)
    return deps
