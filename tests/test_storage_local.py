"""本地文件存储测试。"""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture
def storage():
    from umcp_core.shared.storage.local import LocalStorage
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield LocalStorage(root_dir=tmp_dir)


def test_storage_upload_returns_file_meta(storage):
    meta = storage.upload(
        content=b"hello",
        filename="test.txt",
        uploader_id="u_1",
        file_type="AVATAR",
        biz_type="user",
        biz_id="u_1",
        mime="text/plain",
    )
    assert meta.file_id
    assert meta.filename == "test.txt"
    assert meta.size == 5
    assert meta.mime == "text/plain"


def test_storage_download_returns_content(storage):
    meta = storage.upload(b"hello", "test.txt", "u_1", "AVATAR", "user", "u_1", "text/plain")
    content = storage.download(meta.file_id)
    assert content == b"hello"


def test_storage_delete_removes_file(storage):
    meta = storage.upload(b"hello", "test.txt", "u_1", "AVATAR", "user", "u_1", "text/plain")
    storage.delete(meta.file_id)
    assert storage.download(meta.file_id) is None


def test_storage_get_signed_url_returns_path(storage):
    meta = storage.upload(b"hello", "test.txt", "u_1", "AVATAR", "user", "u_1", "text/plain")
    url = storage.get_signed_url(meta.file_id, expire_sec=3600)
    assert url  # 非空
    assert meta.file_id in url or "test" in url
