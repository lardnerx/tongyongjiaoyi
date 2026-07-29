"""路由聚合。"""

from umcp_core.transport.routers.auth import router as auth_router
from umcp_core.transport.routers.deals import router as deals_router
from umcp_core.transport.routers.events import router as events_router
from umcp_core.transport.routers.health import router as health_router
from umcp_core.transport.routers.matches import router as matches_router
from umcp_core.transport.routers.resources import router as resources_router
from umcp_core.transport.routers.tasks import router as tasks_router
from umcp_core.transport.routers.trust import router as trust_router


def register_routers(app) -> None:
    """注册全部路由。"""
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1/auth")
    app.include_router(tasks_router, prefix="/api/v1/tasks")
    app.include_router(resources_router, prefix="/api/v1/resources")
    app.include_router(matches_router, prefix="/api/v1/matches")
    app.include_router(deals_router, prefix="/api/v1/deals")
    app.include_router(trust_router, prefix="/api/v1/trust")
    app.include_router(events_router, prefix="/api/v1/events")
