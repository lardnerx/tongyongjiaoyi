"""站内通知（4.2 通知留痕）测试：仓储 + API。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from umcp_core.server import UMCPServer
from umcp_core.shared.notification.base import Notification
from umcp_core.shared.notification.repository import InMemoryNotificationRepository
from umcp_core.transport.app import create_app
from umcp_core.transport.auth import JwtService, _ClaimsDemander, _ClaimsUser
from umcp_core.transport.config import TransportConfig


@pytest.fixture
def client_and_server():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    app = create_app(server, TransportConfig(jwt_secret="test-secret"))
    with TestClient(app) as client:
        yield client, server


def _headers(user_id: str) -> dict[str, str]:
    jwt = JwtService("test-secret")
    user = _ClaimsUser(user_id=user_id, name="测试用户")
    user.add_role(_ClaimsDemander())
    tokens = jwt.issue(user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestInMemoryNotificationRepository:
    def test_save_and_list_newest_first(self):
        repo = InMemoryNotificationRepository()
        repo.save(Notification(user_id="u1", event_type="A", title="第一条", body="b1"))
        repo.save(Notification(user_id="u1", event_type="B", title="第二条", body="b2"))

        rows = repo.list_by_user("u1")
        assert [r["title"] for r in rows] == ["第二条", "第一条"]

    def test_list_isolated_by_user(self):
        repo = InMemoryNotificationRepository()
        repo.save(Notification(user_id="u1", event_type="A", title="u1", body=""))
        repo.save(Notification(user_id="u2", event_type="A", title="u2", body=""))

        assert len(repo.list_by_user("u1")) == 1
        assert repo.list_by_user("u2")[0]["title"] == "u2"

    def test_mark_read_and_count(self):
        repo = InMemoryNotificationRepository()
        nid = repo.save(Notification(user_id="u1", event_type="A", title="t", body=""))
        assert repo.count_unread("u1") == 1

        assert repo.mark_read("u1", nid) is True
        assert repo.count_unread("u1") == 0
        assert repo.list_by_user("u1", unread_only=True) == []

    def test_mark_read_rejects_other_user(self):
        repo = InMemoryNotificationRepository()
        nid = repo.save(Notification(user_id="u1", event_type="A", title="t", body=""))

        assert repo.mark_read("u2", nid) is False
        assert repo.count_unread("u1") == 1

    def test_mark_all_read(self):
        repo = InMemoryNotificationRepository()
        repo.save(Notification(user_id="u1", event_type="A", title="a", body=""))
        repo.save(Notification(user_id="u1", event_type="A", title="b", body=""))

        assert repo.mark_all_read("u1") == 2
        assert repo.count_unread("u1") == 0


class TestNotificationApi:
    def test_notify_persists_and_lists(self, client_and_server):
        client, server = client_and_server
        server.notification_center.notify(
            user_id="u1",
            event_type="DEAL_CREATED",
            channels=[],
            params={"deal_id": "d1"},
            title="新订单",
            body="有一位学员下单",
        )

        resp = client.get("/api/v1/notifications", headers=_headers("u1"))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_unread"] == 1
        assert data["items"][0]["title"] == "新订单"
        assert data["items"][0]["is_read"] is False

    def test_list_only_returns_own_messages(self, client_and_server):
        client, server = client_and_server
        server.notification_center.notify("u1", "A", [], {}, title="给u1")
        server.notification_center.notify("u2", "A", [], {}, title="给u2")

        data = client.get("/api/v1/notifications", headers=_headers("u1")).json()["data"]
        assert [i["title"] for i in data["items"]] == ["给u1"]

    def test_unread_count_and_mark_read(self, client_and_server):
        client, server = client_and_server
        server.notification_center.notify("u1", "A", [], {}, title="t1")
        server.notification_center.notify("u1", "A", [], {}, title="t2")

        count = client.get(
            "/api/v1/notifications/unread-count", headers=_headers("u1")
        ).json()["data"]["count"]
        assert count == 2

        nid = client.get(
            "/api/v1/notifications", headers=_headers("u1")
        ).json()["data"]["items"][0]["notification_id"]
        resp = client.post(f"/api/v1/notifications/{nid}/read", headers=_headers("u1"))
        assert resp.status_code == 200
        assert client.get(
            "/api/v1/notifications/unread-count", headers=_headers("u1")
        ).json()["data"]["count"] == 1

    def test_mark_read_not_found(self, client_and_server):
        client, _ = client_and_server
        resp = client.post("/api/v1/notifications/999/read", headers=_headers("u1"))
        assert resp.status_code == 404

    def test_mark_all_read(self, client_and_server):
        client, server = client_and_server
        for i in range(3):
            server.notification_center.notify("u1", "A", [], {}, title=f"t{i}")

        resp = client.post("/api/v1/notifications/read-all", headers=_headers("u1"))
        assert resp.status_code == 200
        assert resp.json()["data"]["marked"] == 3
        assert client.get(
            "/api/v1/notifications/unread-count", headers=_headers("u1")
        ).json()["data"]["count"] == 0

    def test_requires_auth(self, client_and_server):
        client, _ = client_and_server
        assert client.get("/api/v1/notifications").status_code == 401
