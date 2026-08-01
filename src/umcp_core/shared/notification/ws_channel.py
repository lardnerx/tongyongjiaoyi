"""WebSocket 通知渠道（复用 umcp-core 的 ConnectionManager）。"""
from __future__ import annotations

import asyncio
from typing import Any

from umcp_core.shared.notification.base import NotificationChannel, Notification


class WSNotificationChannel(NotificationChannel):
    """WebSocket 推送渠道。

    依赖 umcp-core 的 transport.ws.ConnectionManager，
    通过 send_to_user 推送消息给在线用户。
    """

    def __init__(self, ws_manager: Any) -> None:
        self._ws_manager = ws_manager

    @property
    def name(self) -> str:
        return "WS_PUSH"

    def send(self, user_id: str, notification: Notification) -> None:
        message = {
            "type": "notification",
            "event_type": notification.event_type,
            "title": notification.title,
            "body": notification.body,
            "params": notification.params,
        }
        # ConnectionManager.send_to_user 是 async，用 ensure_future 触发
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._ws_manager.send_to_user(user_id, message))
            else:
                loop.run_until_complete(self._ws_manager.send_to_user(user_id, message))
        except RuntimeError:
            # 无事件循环，跳过（开发期可接受）
            pass
