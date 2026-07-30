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
    """就绪检查：检查 server + 仓储 + DB 连通性。"""
    ready_status = {
        "server_running": server.is_running,
        "task_repo": server.task_repo is not None,
    }
    # DB 连通性检查
    if hasattr(server, "_postgres_bundle"):
        try:
            server.task_repo.list_all()
            ready_status["db_connected"] = True
        except Exception:
            ready_status["db_connected"] = False
    else:
        ready_status["db_connected"] = "in-memory"
    all_ready = all(
        v for v in ready_status.values() if isinstance(v, bool)
    )
    return ok(data={"ready": all_ready, "components": ready_status})
