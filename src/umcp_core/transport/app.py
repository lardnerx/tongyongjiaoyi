"""FastAPI 应用工厂。"""

from __future__ import annotations

import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.deps import get_jwt_service, get_server
from umcp_core.transport.errors import InvalidCredentialError, register_exception_handlers
from umcp_core.transport.metrics import MetricsMiddleware, metrics_response
from umcp_core.transport.routers import register_routers
from umcp_core.transport.ws import ConnectionManager, make_ws_event_bridge

logger = logging.getLogger(__name__)

_LOG_CONF_PATH = Path(__file__).resolve().parent.parent.parent.parent / "logging.conf"


def _setup_logging() -> None:
    """加载统一日志配置（若 logging.conf 存在）。"""
    if _LOG_CONF_PATH.exists():
        logging.config.fileConfig(_LOG_CONF_PATH, disable_existing_loggers=False)


def create_app(server: UMCPServer, config: TransportConfig) -> FastAPI:
    """创建 FastAPI 应用。

    Args:
        server: 已配置好的 UMCPServer（含仓储、插件、策略）
        config: 传输层配置

    Returns:
        FastAPI 应用实例
    """
    _setup_logging()
    jwt_service = JwtService(
        secret=config.jwt_secret,
        access_ttl=config.jwt_access_ttl,
        refresh_ttl=config.jwt_refresh_ttl,
    )
    ws_manager = ConnectionManager()
    ws_bridge_ref: dict = {"bridge": None, "loop": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        loop = asyncio.get_event_loop()
        ws_bridge_ref["loop"] = loop
        bridge = make_ws_event_bridge(ws_manager, loop)
        ws_bridge_ref["bridge"] = bridge
        server.event_bus.subscribe_all(bridge)
        logger.info("UMCP HTTP 服务已启动")
        yield
        # shutdown
        if ws_bridge_ref["bridge"]:
            server.event_bus.unsubscribe_all(ws_bridge_ref["bridge"])
        await ws_manager.disconnect_all()
        server.stop()
        server.dispose()
        logger.info("UMCP HTTP 服务已停止")

    app = FastAPI(
        title="UMCP HTTP API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 状态注入
    app.state.server = server
    app.state.jwt_service = jwt_service
    app.state.ws_manager = ws_manager
    app.state.config = config

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Prometheus 指标中间件
    app.add_middleware(MetricsMiddleware)

    # 异常处理器
    register_exception_handlers(app)

    # 路由
    register_routers(app)

    # Prometheus /metrics 端点（不走 /api/v1 前缀，便于 scrape 配置）
    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus 指标端点。"""
        return metrics_response()

    # WebSocket 端点
    @app.websocket("/api/v1/ws/events")
    async def ws_events(
        ws: WebSocket,
        token: str | None = Query(default=None),
    ) -> None:
        """WebSocket 事件推送端点。

        客户端通过 query 参数 ?token=<access_token> 认证。
        """
        if not token:
            await ws.close(code=4001, reason="缺少 token")
            return
        try:
            payload = jwt_service.decode(token)
        except Exception:
            await ws.close(code=4001, reason="token 无效")
            return
        if jwt_service.is_revoked(payload.get("jti", "")):
            await ws.close(code=4001, reason="token 已吊销")
            return

        from umcp_core.transport.auth import user_from_claims
        user = user_from_claims(payload)
        await ws_manager.connect(ws, user)
        try:
            while True:
                # 接收客户端消息（保活；客户端可发 ping/pong）
                msg = await ws.receive_text()
                # 忽略客户端消息，或处理 ping
                if msg == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            await ws_manager.disconnect(ws, user)

    return app
