"""Pydantic 请求/响应模型：统一信封 + 分页。"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """统一响应信封。code=0 成功，非 0 失败。"""

    code: int = 0
    data: T | None = None
    message: str = "ok"


class ErrorEnvelope(BaseModel):
    """错误响应信封。"""

    code: int
    message: str
    details: Any = None


class PaginatedData(BaseModel, Generic[T]):
    """分页数据。"""

    items: list[T]
    total: int
    page: int
    size: int


class PaginationParams(BaseModel):
    """分页查询参数。"""

    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


def ok(data: Any = None, message: str = "ok") -> Envelope:
    """构造成功响应。"""
    return Envelope(code=0, data=data, message=message)


def paginated(items: list[Any], total: int, page: int, size: int) -> Envelope:
    """构造分页成功响应。"""
    return Envelope(code=0, data=PaginatedData(items=items, total=total, page=page, size=size))
