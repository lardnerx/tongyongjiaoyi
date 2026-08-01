"""文件存储抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileMeta:
    """文件元信息。"""

    file_id: str
    uploader_id: str
    filename: str
    url: str
    file_type: str
    biz_type: str
    biz_id: str
    size: int
    mime: str
    created_at: datetime


class FileStorage(ABC):
    """文件存储抽象基类。"""

    @abstractmethod
    def upload(
        self,
        content: bytes,
        filename: str,
        uploader_id: str,
        file_type: str,
        biz_type: str,
        biz_id: str,
        mime: str,
    ) -> FileMeta:
        """上传文件。"""

    @abstractmethod
    def download(self, file_id: str) -> bytes | None:
        """下载文件内容。不存在返回 None。"""

    @abstractmethod
    def get_signed_url(self, file_id: str, expire_sec: int = 3600) -> str:
        """获取签名访问 URL。"""

    @abstractmethod
    def delete(self, file_id: str) -> None:
        """删除文件。"""
