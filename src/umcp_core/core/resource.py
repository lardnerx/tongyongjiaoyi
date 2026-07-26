"""Resource 与 Capability 抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from umcp_core.core.domain import DomainTag, generate_id


class ResourceStatus:
    """资源状态枚举。"""

    OFFLINE = "offline"
    IDLE = "idle"
    BUSY = "busy"
    DISABLED = "disabled"

    ALL: tuple[str, ...] = (OFFLINE, IDLE, BUSY, DISABLED)


class Capability:
    """可组合、可独立验证的能力单元。

    type ∈ {"skill", "certification", "equipment", "location"}
    """

    def __init__(
        self,
        type: str,
        name: str,
        value: str = "",
        verified: bool = False,
        expiry: datetime | None = None,
    ) -> None:
        self.type: str = type
        self.name: str = name
        self.value: str = value
        self.verified: bool = verified
        self.expiry: datetime | None = expiry

    def is_expired(self) -> bool:
        return self.expiry is not None and self.expiry < datetime.utcnow()

    def is_valid(self) -> bool:
        return self.verified and not self.is_expired()

    def __repr__(self) -> str:
        return f"<Capability {self.type}:{self.name}={self.value} verified={self.verified}>"


class Resource(ABC):
    """供给资源根抽象。

    资源是供给方的可调度单元（司机、设计师、车辆等）。
    """

    def __init__(
        self,
        supplier_id: str,
        domain_tag: DomainTag,
        resource_id: str | None = None,
        capabilities: list[Capability] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.resource_id: str = resource_id or generate_id("res")
        self.supplier_id: str = supplier_id
        self.domain_tag: DomainTag = domain_tag
        self.status: str = ResourceStatus.OFFLINE
        self.capabilities: list[Capability] = capabilities or []
        self.metadata: dict[str, Any] = metadata or {}
        self.created_at: datetime = datetime.utcnow()
        self.updated_at: datetime = datetime.utcnow()

    @abstractmethod
    def resource_type(self) -> str:
        """返回资源类型标识，如 'driver'、'designer'。"""

    def register(self) -> None:
        """资源上线。"""
        if self.status == ResourceStatus.DISABLED:
            raise RuntimeError("资源已被禁用，无法上线")
        self.status = ResourceStatus.IDLE
        self.updated_at = datetime.utcnow()

    def update_status(self, new_status: str) -> None:
        """更新资源状态。"""
        if new_status not in ResourceStatus.ALL:
            raise ValueError(f"未知资源状态: {new_status}")
        self.status = new_status
        self.updated_at = datetime.utcnow()

    def validate_capability(self, cap: Capability) -> bool:
        """校验资源是否具备某项能力（按 name 匹配，且能力有效）。"""
        for c in self.capabilities:
            if c.name == cap.name and c.is_valid():
                return True
        return False

    def has_capability(self, name: str) -> bool:
        return any(c.name == name and c.is_valid() for c in self.capabilities)

    def add_capability(self, cap: Capability) -> None:
        self.capabilities.append(cap)
        self.updated_at = datetime.utcnow()

    def is_available(self) -> bool:
        return self.status == ResourceStatus.IDLE

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id={self.resource_id} "
            f"domain={self.domain_tag} status={self.status}>"
        )
