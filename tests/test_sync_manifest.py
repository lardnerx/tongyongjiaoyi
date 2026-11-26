"""deploy/sync-manifest.txt 自动化校验工具的测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_sync_manifest as csm  # noqa: E402


class TestLoadManifest:
    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        manifest = tmp_path / "sync-manifest.txt"
        manifest.write_text(
            "# 注释\n\nsrc/umcp_core/server.py\n  \nplugins/a.py\n", encoding="utf-8"
        )
        assert csm.load_manifest(manifest) == [
            "src/umcp_core/server.py",
            "plugins/a.py",
        ]


class TestIsDeployable:
    @pytest.mark.parametrize(
        "path",
        [
            "src/umcp_core/server.py",
            "plugins/escort_driving/plugin.json",
            "web/src/app/layout.tsx",
            "deploy/backup.sh",
            ".env.example",
        ],
    )
    def test_deployable_paths(self, path: str) -> None:
        assert csm.is_deployable(path)

    @pytest.mark.parametrize(
        "path",
        [
            "tests/test_server.py",
            "plugins/escort_driving/tests/test_tasks.py",
            "web/src/components/__tests__/x.test.tsx",
            "scripts/check_sync_manifest.py",
            "docs/README.md",
            "examples/demo.py",
            "migrations/001_init.sql",
            "web/node_modules/react/index.js",
            "web/.next/build.js",
            "pyproject.toml",
            "deploy/sync-manifest.txt",
            "deploy/sync.sh",
        ],
    )
    def test_non_deployable_paths(self, path: str) -> None:
        assert not csm.is_deployable(path)


class TestParseNameStatus:
    def test_modified_deleted_and_renamed(self) -> None:
        text = (
            "M\tsrc/umcp_core/server.py\n"
            "D\tplugins/old.py\n"
            "R100\tplugins/a.py\tplugins/b.py\n"
            "A\tplugins/escort_driving/components.py\n"
        )
        changed, deleted = csm.parse_name_status(text)
        assert changed == [
            "src/umcp_core/server.py",
            "plugins/b.py",
            "plugins/escort_driving/components.py",
        ]
        assert deleted == ["plugins/old.py"]


class TestFindIssues:
    def test_missing_and_orphan(self) -> None:
        changed = [
            "src/umcp_core/server.py",  # 已登记
            "plugins/escort_driving/components.py",  # 未登记
            "tests/test_server.py",  # 非发布文件，忽略
        ]
        deleted = ["plugins/legacy.py", "src/umcp_core/other.py"]
        manifest = ["src/umcp_core/server.py", "plugins/legacy.py"]

        missing, orphans = csm.find_issues(changed, deleted, manifest)

        assert missing == ["plugins/escort_driving/components.py"]
        assert orphans == ["plugins/legacy.py"]

    def test_no_issue_when_covered(self) -> None:
        missing, orphans = csm.find_issues(
            ["plugins/a.py"], [], ["plugins/a.py"]
        )
        assert missing == [] and orphans == []


class TestAppendMissing:
    def test_appends_without_touching_existing(self, tmp_path: Path) -> None:
        manifest = tmp_path / "sync-manifest.txt"
        manifest.write_text("plugins/a.py", encoding="utf-8")

        csm.append_missing(manifest, ["plugins/b.py", "plugins/c.py"])

        assert csm.load_manifest(manifest) == [
            "plugins/a.py",
            "plugins/b.py",
            "plugins/c.py",
        ]

    def test_noop_when_empty(self, tmp_path: Path) -> None:
        manifest = tmp_path / "sync-manifest.txt"
        manifest.write_text("plugins/a.py\n", encoding="utf-8")

        csm.append_missing(manifest, [])

        assert manifest.read_text(encoding="utf-8") == "plugins/a.py\n"


class TestRealManifest:
    """仓库内真实清单的自洽性：无重复、条目文件均存在。"""

    def test_entries_unique(self) -> None:
        entries = csm.load_manifest()
        duplicates = sorted({p for p in entries if entries.count(p) > 1})
        assert duplicates == []

    def test_entries_exist(self) -> None:
        missing = [p for p in csm.load_manifest() if not (REPO_ROOT / p).exists()]
        assert missing == []
