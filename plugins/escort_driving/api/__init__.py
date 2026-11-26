"""陪驾业务 HTTP 路由。

路由随插件一起注册：插件 ``register_plugin`` 调用 ``server.register_router``，
由 ``umcp_core.transport.app.create_app`` 在构建应用时统一挂载，
核心库不再感知陪驾业务路径。
"""

from __future__ import annotations

from .coaches import router as coaches_router
from .deals import router as escort_deals_router
from .orders import router as orders_router
from .payments import router as escort_payments_router
from .reviews import router as reviews_router

# 注册顺序与原有核心静态注册保持一致
ROUTERS = (
    coaches_router,
    orders_router,
    reviews_router,
    escort_payments_router,
    escort_deals_router,
)

__all__ = [
    "ROUTERS",
    "coaches_router",
    "escort_deals_router",
    "orders_router",
    "escort_payments_router",
    "reviews_router",
]
