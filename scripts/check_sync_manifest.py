#!/usr/bin/env python3
"""校验 deploy/sync-manifest.txt 是否覆盖本次改动的可发布文件。

背景：服务器无法直连 GitHub，发布由 deploy/sync.sh 按清单逐个文件从
jsDelivr 拉取。清单漏项会让线上代码与仓库不一致（典型表现：重启后
ImportError、路由 404），因此提交前应做一次自动校验。

用法：
    python scripts/check_sync_manifest.py                     # 校验工作区未提交改动
    python scripts/check_sync_manifest.py --range HEAD~1..HEAD
    python scripts/check_sync_manifest.py --base 28ec7f1 --head dbf05ae
    python scripts/check_sync_manifest.py --uncommitted --fix # 自动补全缺失条目

退出码：0 通过；1 存在漏项/失效条目；2 git 调用失败。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "deploy" / "sync-manifest.txt"

# 需要随发布同步的路径前缀（相对仓库根目录）
DEPLOY_PREFIXES = ("src/", "plugins/", "web/", "deploy/")
# 仓库根目录下需要同步的独立文件
DEPLOY_ROOT_FILES = (".env.example",)
# 不参与发布的目录（测试/文档/示例/开发脚本）
EXCLUDED_PREFIXES = ("tests/", "docs/", "examples/", "migrations/", "scripts/")
# 由 sync.sh 自身固定拉取、不应写进清单的文件
# （sync.sh 若同步自己，会在运行中被覆盖）
SKIP_FILES = ("deploy/sync-manifest.txt", "deploy/sync.sh")
# 路径中包含以下片段时视为测试或构建产物，不参与发布
EXCLUDED_PARTS = (
    "/tests/",
    "/__tests__/",
    "/__pycache__/",
    "/node_modules/",
    "/.next/",
)


def normalize(path: str) -> str:
    return path.replace("\\", "/").strip()


def load_manifest(path: Path = MANIFEST_PATH) -> list[str]:
    """读取清单条目（忽略注释与空行，保持原顺序）。"""
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


def is_deployable(path: str) -> bool:
    """判断仓库内文件是否需要进入发布清单。"""
    normalized = normalize(path)
    if normalized in DEPLOY_ROOT_FILES:
        return True
    if normalized in SKIP_FILES:
        return False
    if normalized.startswith(EXCLUDED_PREFIXES):
        return False
    if any(part in normalized for part in EXCLUDED_PARTS):
        return False
    return normalized.startswith(DEPLOY_PREFIXES)


def parse_name_status(text: str) -> tuple[list[str], list[str]]:
    """解析 ``git diff --name-status`` 输出，返回 (变更文件, 删除文件)。

    重命名/复制取目标路径；删除记录原路径（用于发现清单中的失效条目）。
    """
    changed: list[str] = []
    deleted: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("D"):
            deleted.append(normalize(parts[-1]))
        elif status.startswith(("A", "C", "M", "R", "T", "U")):
            changed.append(normalize(parts[-1]))
    return changed, deleted


def _git(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr.strip()}")
    return result.stdout


def collect_changes(
    base: str | None = None,
    head: str | None = None,
    uncommitted: bool = False,
    repo_root: Path = REPO_ROOT,
) -> tuple[list[str], list[str]]:
    """收集指定范围内的变更与删除文件。"""
    changed: list[str] = []
    deleted: list[str] = []
    if base and head:
        text = _git(
            ["diff", "--name-status", "--find-renames", base, head], repo_root
        )
        c, d = parse_name_status(text)
        changed.extend(c)
        deleted.extend(d)
    if uncommitted:
        text = _git(["diff", "--name-status", "--find-renames", "HEAD"], repo_root)
        c, d = parse_name_status(text)
        changed.extend(c)
        deleted.extend(d)
        # 新增但未跟踪的文件不会出现在 git diff 中
        untracked = _git(["ls-files", "--others", "--exclude-standard"], repo_root)
        changed.extend(
            normalize(line) for line in untracked.splitlines() if line.strip()
        )
    return changed, deleted


def find_issues(
    changed: list[str],
    deleted: list[str],
    manifest: list[str],
) -> tuple[list[str], list[str]]:
    """返回 (清单缺失条目, 清单失效条目)。"""
    listed = set(manifest)
    missing = sorted({p for p in changed if is_deployable(p)} - listed)
    orphans = sorted({p for p in deleted if p in listed})
    return missing, orphans


def append_missing(path: Path, missing: list[str]) -> None:
    """把缺失条目追加到清单末尾（保持原有内容不变）。"""
    if not missing:
        return
    existing = path.read_text(encoding="utf-8")
    if not existing.endswith("\n"):
        existing += "\n"
    path.write_text(
        existing + "\n".join(missing) + "\n", encoding="utf-8", newline="\n"
    )


def _parse_range(value: str) -> tuple[str, str]:
    if ".." not in value:
        raise argparse.ArgumentTypeError("--range 需形如 BASE..HEAD")
    base, head = value.split("..", 1)
    if not base or not head:
        raise argparse.ArgumentTypeError("--range 需形如 BASE..HEAD")
    return base, head


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验发布同步清单覆盖情况")
    parser.add_argument("--base", help="对比的起始提交")
    parser.add_argument("--head", help="对比的结束提交（配合 --base）")
    parser.add_argument("--range", type=_parse_range, help="等价于 --base A --head B")
    parser.add_argument(
        "--uncommitted", action="store_true", help="校验工作区未提交改动"
    )
    parser.add_argument("--fix", action="store_true", help="自动追加缺失条目")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH), help="清单路径")
    args = parser.parse_args(argv)

    base, head = args.base, args.head
    if args.range:
        base, head = args.range
    if not base and not args.uncommitted:
        args.uncommitted = True
    if base and not head:
        head = "HEAD"

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = REPO_ROOT / manifest_path
    if not manifest_path.exists():
        print(f"[FAIL] 清单不存在: {manifest_path}", file=sys.stderr)
        return 2

    try:
        changed, deleted = collect_changes(base, head, args.uncommitted)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    manifest = load_manifest(manifest_path)
    missing, orphans = find_issues(changed, deleted, manifest)

    if missing and args.fix:
        append_missing(manifest_path, missing)
        print(f"[FIX] 已补入 {len(missing)} 个条目: {manifest_path.relative_to(REPO_ROOT)}")
        manifest = load_manifest(manifest_path)
        missing, orphans = find_issues(changed, deleted, manifest)

    if missing:
        print("[FAIL] 以下文件已改动但未加入 deploy/sync-manifest.txt：")
        for path in missing:
            print(f"  + {path}")
    if orphans:
        print("[FAIL] 以下文件已删除但仍留在 deploy/sync-manifest.txt：")
        for path in orphans:
            print(f"  - {path}")

    if missing or orphans:
        hint = (
            "请手工补充/移除清单条目后重试，"
            "或执行 python scripts/check_sync_manifest.py --fix"
        )
        print(hint, file=sys.stderr)
        return 1

    scope = "工作区" if args.uncommitted and not base else f"{base}..{head}"
    print(f"[OK] {scope} 变更均已覆盖清单（名单 {len(manifest)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
