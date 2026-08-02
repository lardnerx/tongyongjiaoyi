"""陪驾业务 router 分区。"""

from umcp_core.transport.routers.escort.coaches import router as coaches_router
from umcp_core.transport.routers.escort.orders import router as orders_router
from umcp_core.transport.routers.escort.reviews import router as reviews_router

__all__ = ["coaches_router", "orders_router", "reviews_router"]
