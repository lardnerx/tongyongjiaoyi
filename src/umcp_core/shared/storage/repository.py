"""文件元信息仓储 ORM。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class FileModel(Base):
    """文件存储表。"""

    __tablename__ = "files"

    file_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    uploader_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False)
    biz_id: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
