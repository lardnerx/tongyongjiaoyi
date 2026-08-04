"""路由聚合。"""

from umcp_core.transport.routers.admin.rules import router as admin_rules_router
from umcp_core.transport.routers.auth import router as auth_router
from umcp_core.transport.routers.deals import router as deals_router
from umcp_core.transport.routers.escort import coaches_router, escort_deals_router, orders_router, escort_payments_router, reviews_router
from umcp_core.transport.routers.events import router as events_router
from umcp_core.transport.routers.friends import router as friends_router
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
    # 陪驾业务 router（prefix 已内置于 router）
    app.include_router(coaches_router)
    app.include_router(orders_router)
    app.include_router(reviews_router)
    app.include_router(escort_payments_router)
    app.include_router(escort_deals_router)
    # 管理员规则配置 router（prefix 已内置于 router）
    app.include_router(admin_rules_router)
    # 好友社交 router（prefix 已内置于 router）
    app.include_router(friends_router)
