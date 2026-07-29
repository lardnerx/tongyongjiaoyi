"""HTTP/WS 传输层（阶段五B）。

将 UMCPServer 暴露为 FastAPI 应用，提供 RESTful API 和 WebSocket 推送。
"""

from umcp_core.transport.app import create_app

__all__ = ["create_app"]
