"""通知中心测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def notification_center():
    from umcp_core.shared.notification.center import NotificationCenter
    from umcp_core.shared.notification.ws_channel import WSNotificationChannel
    center = NotificationCenter()
    center.register_channel("WS_PUSH", WSNotificationChannel(ws_manager=_FakeWSManager()))
    return center


class _FakeWSManager:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_to_user(self, user_id: str, message: dict) -> None:
        self.sent.append({"user_id": user_id, "message": message})


def test_notification_center_notify_dispatches_to_registered_channel(notification_center):
    received = []

    notification_center.register_channel("IN_APP", lambda user_id, payload: received.append((user_id, payload)))
    notification_center.notify(
        user_id="u_1",
        event_type="DEAL_CREATED",
        channels=["WS_PUSH", "IN_APP"],
        params={"deal_id": "d_1"},
    )
    # IN_APP 是同步 lambda
    assert ("u_1", {"deal_id": "d_1"}) in received


def test_notification_center_notify_skips_unregistered_channels(notification_center):
    # 只注册了 WS_PUSH，IN_APP 未注册时不抛异常
    notification_center.notify(
        user_id="u_1",
        event_type="DEAL_CREATED",
        channels=["WS_PUSH", "UNKNOWN_CHANNEL"],
        params={"deal_id": "d_1"},
    )
    # 不抛异常即通过


def test_notification_center_notify_both(notification_center):
    received = []
    notification_center.register_channel("IN_APP", lambda user_id, payload: received.append(user_id))
    notification_center.notify_both(
        user_id_a="student_1",
        user_id_b="coach_1",
        event_type="DEAL_CONFIRMED",
        channels=["IN_APP"],
        params={"deal_id": "d_1"},
    )
    assert "student_1" in received
    assert "coach_1" in received
