"""位置信息仓储（PostGIS）。

注：实际 PostGIS 实现需要 geoalchemy2，本计划阶段先用内存 LBS，
PostGIS 仓储骨架在此占位以便后续计划接入。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class LocationModel(Base):
    """位置信息表（PostGIS geometry 列在迁移中用 raw SQL 创建）。"""

    __tablename__ = "lbs_locations"

    location_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 注意：geometry 列需在迁移中用 SELECT AddGeometryColumn 创建，
    # 这里不映射为 ORM 属性，仅作占位
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
