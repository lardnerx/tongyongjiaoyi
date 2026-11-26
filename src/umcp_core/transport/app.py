"""FastAPI 应用工厂。"""

from __future__ import annotations

import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from umcp_core.core.base import User
from umcp_core.core.domain import Credential
from umcp_core.layers.l1 import PhoneAuthProvider
from umcp_core.server import UMCPServer
from umcp_core.transport.auth import JwtService
from umcp_core.transport.config import TransportConfig
from umcp_core.transport.deps import get_jwt_service, get_server
from umcp_core.transport.errors import InvalidCredentialError, register_exception_handlers
from umcp_core.transport.metrics import MetricsMiddleware, metrics_response
from umcp_core.transport.routers import register_routers
from umcp_core.transport.scheduler import SchedulerService
from umcp_core.transport.ws import ConnectionManager, make_ws_event_bridge
from umcp_core.transport.workers.realtime_cancel_worker import RealtimeCancelWorker
from umcp_core.transport.workers.payment_timeout_worker import PaymentTimeoutWorker

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

    # 应用认证缓存 TTL 配置（灰度测试用，通过环境变量 UMCP_AUTH_CACHE_TTL 控制）
    if isinstance(server.auth_provider, PhoneAuthProvider):
        server.auth_provider._cache_ttl = config.auth_cache_ttl

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        loop = asyncio.get_event_loop()
        ws_bridge_ref["loop"] = loop
        bridge = make_ws_event_bridge(ws_manager, loop)
        ws_bridge_ref["bridge"] = bridge
        server.event_bus.subscribe_all(bridge)
        # 启动调度器服务（注册 Worker）
        scheduler = SchedulerService(interval_seconds=1.0)
        scheduler.register(RealtimeCancelWorker())
        scheduler.register(PaymentTimeoutWorker())
        app.state.scheduler = scheduler
        scheduler_task = asyncio.create_task(scheduler.start(context={"server": server}))
        app.state.scheduler_task = scheduler_task
        logger.info("UMCP HTTP 服务已启动")
        yield
        # shutdown
        await scheduler.stop()
        try:
            await asyncio.wait_for(scheduler_task, timeout=5.0)
        except asyncio.TimeoutError:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
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
    server.ws_manager = ws_manager
    # 如果通知中心已存在，补注册 WS 推送渠道（插件加载时 ws_manager 尚未可用）
    notification_center = getattr(server, "notification_center", None)
    if notification_center is not None:
        try:
            from umcp_core.shared.notification.ws_channel import WSNotificationChannel
            notification_center.register_channel("WS_PUSH", WSNotificationChannel(ws_manager))
            logger.info("[NOTIFY] WS 通知渠道已补注册")
        except Exception as e:
            logger.warning("[NOTIFY] WS 通知渠道补注册失败: %s", e)
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

    # 限流中间件（保护支付回调接口在高频请求下不被打垮）
    if config.rate_limit_enabled:
        from umcp_core.transport.middleware.rate_limit import RateLimitMiddleware

        app.add_middleware(
            RateLimitMiddleware,
            window_seconds=config.rate_limit_window_seconds,
            max_requests=config.rate_limit_max_requests,
            redis_url=config.rate_limit_redis_url,
            # 支付回调本身豁免限流，避免微信回调超时
            exempt_paths=["/api/v1/escort/payments/callback"],
        )
        logger.info("限流中间件已启用: window=%ss max=%s", config.rate_limit_window_seconds, config.rate_limit_max_requests)

    # 异常处理器
    register_exception_handlers(app)

    # 路由：核心通用路由 + 插件注册的业务路由（插件需在 create_app 之前加载）
    register_routers(app)
    for plugin_router, prefix in server.plugin_routers:
        if prefix:
            app.include_router(plugin_router, prefix=prefix)
        else:
            app.include_router(plugin_router)

    # 静态文件服务：挂载上传目录（头像等）
    uploads_dir = Path(__file__).resolve().parent.parent.parent.parent / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/api/v1/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

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
