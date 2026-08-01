"""本地文件存储（开发用，写本地磁盘）。"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

from umcp_core.shared.storage.base import FileMeta, FileStorage


class LocalStorage(FileStorage):
    """本地磁盘存储。"""

    def __init__(self, root_dir: str) -> None:
        self._root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)
        self._metas: dict[str, FileMeta] = {}

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
        file_id = f"file_{uuid.uuid4().hex[:16]}"
        path = os.path.join(self._root_dir, f"{file_id}_{filename}")
        with open(path, "wb") as f:
            f.write(content)
        meta = FileMeta(
            file_id=file_id,
            uploader_id=uploader_id,
            filename=filename,
            url=path,
            file_type=file_type,
            biz_type=biz_type,
            biz_id=biz_id,
            size=len(content),
            mime=mime,
            created_at=datetime.utcnow(),
        )
        self._metas[file_id] = meta
        return meta

    def download(self, file_id: str) -> bytes | None:
        meta = self._metas.get(file_id)
        if meta is None:
            return None
        try:
            with open(meta.url, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def get_signed_url(self, file_id: str, expire_sec: int = 3600) -> str:
        meta = self._metas.get(file_id)
        if meta is None:
            return ""
        return f"file://{meta.url}?expires={expire_sec}"

    def delete(self, file_id: str) -> None:
        meta = self._metas.pop(file_id, None)
        if meta and os.path.exists(meta.url):
            os.remove(meta.url)
