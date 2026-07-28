"""core 包：核心抽象类。"""

from umcp_core.core.base import Demander, PermissionSet, Role, Supplier, User
from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.domain import (
    Attachment,
    Credential,
    DomainTag,
    SpatioTemporalConstraint,
    generate_id,
)
from umcp_core.core.resource import Capability, Resource, ResourceStatus
from umcp_core.core.task import CustomTask, PackageTask, StandardTask, Task, TaskStatus

__all__ = [
    "User",
    "Role",
    "Demander",
    "Supplier",
    "PermissionSet",
    "Task",
    "StandardTask",
    "CustomTask",
    "PackageTask",
    "CompositeTask",
    "TaskStatus",
    "Resource",
    "Capability",
    "ResourceStatus",
    "Deal",
    "DealStatus",
    "DomainTag",
    "Attachment",
    "Credential",
    "SpatioTemporalConstraint",
    "generate_id",
]
