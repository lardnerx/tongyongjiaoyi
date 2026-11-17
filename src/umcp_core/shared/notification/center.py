"""通知中心：多渠道分发 + 模板渲染 + 站内消息留痕。"""
from __future__ import annotations

import logging
from typing import Any, Callable

from umcp_core.shared.notification.base import FunctionChannel, Notification, NotificationChannel

logger = logging.getLogger(__name__)


class NotificationCenter:
    """通知中心。

    - register_channel：注册渠道
    - notify：向单个用户多渠道分发，并写入站内消息表
    - notify_both：向双方分发（如学员+教练）
    """

    def __init__(self, store: Any | None = None) -> None:
        self._channels: dict[str, NotificationChannel] = {}
        self._templates: dict[str, dict[str, Any]] = {}
        self._store = store

    def register_channel(self, name: str, channel: NotificationChannel | Callable) -> None:
        """注册渠道。channel 可为 NotificationChannel 实例或同步函数。"""
        if isinstance(channel, NotificationChannel):
            self._channels[name] = channel
        else:
            self._channels[name] = FunctionChannel(name, channel)

    def register_template(self, event_type: str, title_template: str, body_template: str) -> None:
        """注册通知模板。"""
        self._templates[event_type] = {"title": title_template, "body": body_template}

    def notify(
        self,
        user_id: str,
        event_type: str,
        channels: list[str],
        params: dict[str, Any],
        title: str | None = None,
        body: str | None = None,
    ) -> Notification:
        """向单个用户分发通知。"""
        tpl = self._templates.get(event_type, {})
        notification = Notification(
            user_id=user_id,
            event_type=event_type,
            title=title or tpl.get("title", event_type),
            body=body or tpl.get("body", ""),
            channels=list(channels),
            params=dict(params),
        )
        # 站内消息留痕：落库失败不阻断业务主流程
        if self._store is not None:
            try:
                self._store.save(notification)
            except Exception as e:  # pragma: no cover - 依赖外部存储异常
                logger.warning("[NOTIFY] 站内消息落库失败: %s", e)
        for ch_name in channels:
            channel = self._channels.get(ch_name)
            if channel is None:
                continue  # 未注册的渠道静默跳过
            channel.send(user_id, notification)
        return notification

    def notify_both(
        self,
        user_id_a: str,
        user_id_b: str,
        event_type: str,
        channels: list[str],
        params: dict[str, Any],
    ) -> tuple[Notification, Notification]:
        """向双方分发通知。"""
        n_a = self.notify(user_id_a, event_type, channels, params)
        n_b = self.notify(user_id_b, event_type, channels, params)
        return n_a, n_b
