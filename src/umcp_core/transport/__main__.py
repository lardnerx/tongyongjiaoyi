"""UMCP HTTP 服务入口。

用法：
    python -m umcp_core.transport

环境变量：
    UMCP_JWT_SECRET（必填）
    UMCP_DB_DSN（可选，不填用内存仓储）
    UMCP_HOST（默认 0.0.0.0）
    UMCP_PORT（默认 8000）
"""

from __future__ import annotations

import sys

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig


def main() -> None:
    config = TransportConfig.from_env()
    server = UMCPServer()
    if config.db_dsn:
        server.use_postgres_repositories(config.db_dsn)
    else:
        server.use_in_memory_repositories()
    server.start()
    app = create_app(server, config)

    try:
        import uvicorn
    except ImportError:
        print("请安装 uvicorn: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
