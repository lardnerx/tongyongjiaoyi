"""领域辅助对象：DomainTag、Attachment、SpatioTemporalConstraint、Credential。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DomainTag:
    """领域标签，用于标识任务/资源所属行业。

    例：DomainTag.of("ride")、DomainTag.of("design")。
    """

    value: str

    @classmethod
    def of(cls, value: str) -> DomainTag:
        return cls(value=value.lower())

    def __str__(self) -> str:
        return self.value


@dataclass
class Attachment:
    """任务附件，支持结构化文档。"""

    name: str
    url: str = ""
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    structured_specs: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpatioTemporalConstraint:
    """时空约束（可选）。

    出行类任务有起终点，设计/咨询类任务无地点。
    """

    origin_lat: float | None = None
    origin_lng: float | None = None
    origin_address: str = ""
    dest_lat: float | None = None
    dest_lng: float | None = None
    dest_address: str = ""
    earliest_start: datetime | None = None
    latest_start: datetime | None = None

    def has_location(self) -> bool:
        return self.origin_lat is not None and self.origin_lng is not None


@dataclass
class Credential:
    """认证凭据。"""

    type: str  # phone, email, wechat, api_key, ...
    token: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def phone(cls, phone: str, code: str = "") -> Credential:
        return cls(type="phone", token=phone, payload={"code": code})

    @classmethod
    def email(cls, email: str, password: str = "") -> Credential:
        return cls(type="email", token=email, payload={"password": password})

    @classmethod
    def api_key(cls, key: str) -> Credential:
        return cls(type="api_key", token=key)


def generate_id(prefix: str = "id") -> str:
    """生成带前缀的唯一 ID。"""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"
