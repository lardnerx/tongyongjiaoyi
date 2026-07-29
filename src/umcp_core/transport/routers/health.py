"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_server
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter()


@router.get("/health", response_model=Envelope)
async def health() -> Envelope:
    """存活检查。"""
    return ok(data={"status": "ok"})


@router.get("/health/ready", response_model=Envelope)
async def ready(server: UMCPServer = Depends(get_server)) -> Envelope:
    """就绪检查。"""
    ready_status = {
        "server_running": server.is_running,
        "task_repo": server.task_repo is not None,
    }
    all_ready = all(ready_status.values())
    return ok(data={"ready": all_ready, "components": ready_status})
