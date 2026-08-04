"""好友社交 router（互加好友）。"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from umcp_core.core.base import User
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError, PermissionDeniedError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/friends", tags=["friends"])

# 内存存储（MVP 阶段，后续迁移到 ORM）
_friend_requests_store: dict[str, dict] = {}  # request_id -> request dict
_friendships_store: dict[str, dict] = {}  # friendship_id -> friendship dict
_store_lock = threading.Lock()


class SendFriendRequestModel(BaseModel):
    to_user_id: str
    message: str = ""


class FriendRequestResponse(BaseModel):
    request_id: str
    from_user_id: str
    to_user_id: str
    status: str
    message: str
    created_at: str
    responded_at: str | None = None


def _is_friend(user_id: str, friend_user_id: str) -> bool:
    """检查两人是否已是好友。"""
    for f in _friendships_store.values():
        if (f["user_id"] == user_id and f["friend_user_id"] == friend_user_id) or (
            f["user_id"] == friend_user_id and f["friend_user_id"] == user_id
        ):
            return True
    return False


@router.post("/requests", response_model=Envelope)
async def send_friend_request(
    req: SendFriendRequestModel,
    current_user: User = Depends(get_current_user),
    server: UMCPServer = Depends(get_server),
) -> Envelope:
    """发送好友请求。"""
    from_user_id = current_user.user_id
    to_user_id = req.to_user_id

    # 不能给自己发请求
    if from_user_id == to_user_id:
        raise IllegalStateError(message="不能给自己发送好友请求")

    with _store_lock:
        # 检查是否已是好友
        if _is_friend(from_user_id, to_user_id):
            raise IllegalStateError(message="你们已经是好友了")

        # 检查是否已有 pending 请求（任一方向）
        for r in _friend_requests_store.values():
            if r["status"] != "pending":
                continue
            if (r["from_user_id"] == from_user_id and r["to_user_id"] == to_user_id) or (
                r["from_user_id"] == to_user_id and r["to_user_id"] == from_user_id
            ):
                raise IllegalStateError(message="已有待处理的好友请求")

        request_id = f"freq_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()
        request = {
            "request_id": request_id,
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "status": "pending",
            "message": req.message,
            "created_at": now,
            "responded_at": None,
        }
        _friend_requests_store[request_id] = request

    # 发布事件（payload.user_id 指向接收方，用于 WS 推送）
    server.event_bus.publish(
        Event(
            type=EventType.FRIEND_REQUEST_CREATED,
            source_layer="ESCORT",
            payload={
                "request_id": request_id,
                "from_user_id": from_user_id,
                "user_id": to_user_id,  # 接收方（用于 WS 推送路由）
                "message": req.message,
            },
        )
    )

    return ok(request)


@router.get("/requests", response_model=Envelope)
async def list_received_requests(
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """查看我收到的好友请求（pending 状态）。"""
    with _store_lock:
        requests = [
            r
            for r in _friend_requests_store.values()
            if r["to_user_id"] == current_user.user_id and r["status"] == "pending"
        ]
    # 按创建时间倒序
    requests.sort(key=lambda r: r["created_at"], reverse=True)
    return ok(requests)
