"""工具类。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_plugin_manifest(plugin_path: str | Path) -> dict[str, Any]:
    """加载行业插件描述文件 plugin.json。

    示例 plugin.json 内容参见 CodeWiki.md 6.3 节。
    """
    path = Path(plugin_path)
    if not path.exists():
        raise FileNotFoundError(f"插件描述文件不存在: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def import_class(dotted_path: str) -> type:
    """根据点分路径导入类。

    例：import_class("umcp_core.layers.l3.matching.InstantMatch")
    """
    if "." not in dotted_path:
        raise ValueError(f"无效的点分路径: {dotted_path}")
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    if not hasattr(module, class_name):
        raise AttributeError(f"模块 {module_path} 中未找到类 {class_name}")
    return getattr(module, class_name)


def camel_to_snake(name: str) -> str:
    """驼峰命名转蛇形命名。"""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def snake_to_camel(name: str) -> str:
    """蛇形命名转驼峰命名。"""
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])
