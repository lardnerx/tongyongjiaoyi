"""通知抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class Notification:
    """通知实体。"""

    user_id: str
    event_type: str
    title: str
    body: str
    channels: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class NotificationChannel(ABC):
    """通知渠道抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """渠道名（如 WS_PUSH / SMS / IN_APP）。"""

    @abstractmethod
    def send(self, user_id: str, notification: Notification) -> None:
        """发送通知。"""


class FunctionChannel(NotificationChannel):
    """函数式渠道（测试与 IN_APP 用）。

    func 签名为 (user_id, params_dict)，因此 send 将 notification.params
    传给 func，以匹配测试中的 lambda 签名。
    """

    def __init__(self, channel_name: str, func: Callable[[str, dict[str, Any]], None]) -> None:
        self._name = channel_name
        self._func = func

    @property
    def name(self) -> str:
        return self._name

    def send(self, user_id: str, notification: Notification) -> None:
        self._func(user_id, notification.params)
