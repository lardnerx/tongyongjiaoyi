"""陪驾业务 router 分区。"""

from umcp_core.transport.routers.escort.coaches import router as coaches_router

__all__ = ["coaches_router"]
