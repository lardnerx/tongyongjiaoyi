"""通知模板渲染（Jinja2）。

支持从模板字符串渲染通知标题和内容。
线程安全：每个渲染调用使用独立的 Jinja2 环境。
"""
from __future__ import annotations

import logging
from typing import Any

from jinja2 import Environment, BaseLoader, TemplateNotFound, Undefined, UndefinedError

logger = logging.getLogger(__name__)


class _SilentUndefined(Undefined):
    """静默未定义变量：模板中 {{ var }} 引用不存在的变量时返回空字符串。"""

    def __str__(self) -> str:
        return ""

    def __repr__(self) -> str:
        return ""

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return False

    def __ne__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 0


class _SilentEnvironment(Environment):
    """自定义 Jinja2 环境：未定义变量静默返回空字符串。"""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("undefined", _SilentUndefined)
        super().__init__(**kwargs)


class NotificationTemplate:
    """通知模板。

    用法：
        tpl = NotificationTemplate("订单 {{ order_id }} 已确认", "学员 {{ student_name }} 已确认您的预约。")
        title, body = tpl.render(order_id="123", student_name="张三")
    """

    def __init__(self, title_template: str, body_template: str) -> None:
        self._env = _SilentEnvironment(loader=BaseLoader(), autoescape=False)
        self._title_template = self._env.from_string(title_template)
        self._body_template = self._env.from_string(body_template)

    def render(self, **params: Any) -> tuple[str, str]:
        """渲染标题和正文。"""
        try:
            title = self._title_template.render(**params)
        except (TemplateNotFound, UndefinedError) as e:
            logger.warning("[TEMPLATE] title render failed: %s", e)
            title = ""

        try:
            body = self._body_template.render(**params)
        except (TemplateNotFound, UndefinedError) as e:
            logger.warning("[TEMPLATE] body render failed: %s", e)
            body = ""

        return title, body


class TemplateRegistry:
    """模板注册表。

    管理事件类型到通知模板的映射。
    """

    def __init__(self) -> None:
        self._templates: dict[str, NotificationTemplate] = {}

    def register(
        self,
        event_type: str,
        title_template: str,
        body_template: str,
    ) -> None:
        """注册通知模板。"""
        self._templates[event_type] = NotificationTemplate(title_template, body_template)

    def render(self, event_type: str, **params: Any) -> tuple[str, str]:
        """渲染指定事件类型的通知模板。"""
        tpl = self._templates.get(event_type)
        if tpl is None:
            logger.warning("[TEMPLATE] no template for event_type=%s, using raw", event_type)
            return event_type, str(params)
        return tpl.render(**params)

    def has_template(self, event_type: str) -> bool:
        """检查事件类型是否有已注册的模板。"""
        return event_type in self._templates