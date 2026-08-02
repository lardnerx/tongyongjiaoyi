"""UMCP HTTP 服务入口。

用法：
    python -m umcp_core.transport

环境变量：
    UMCP_JWT_SECRET（必填）
    UMCP_DB_DSN（可选，不填用内存仓储）
    UMCP_HOST（默认 0.0.0.0）
    UMCP_PORT（默认 8000）
    UMCP_PLUGINS（可选，逗号分隔的插件名，如 escort_driving）
"""

from __future__ import annotations

import os
import sys

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig


def main() -> None:
    config = TransportConfig.from_env()
    server = UMCPServer()
    if config.db_dsn:
        server.use_postgres_repositories(
            config.db_dsn,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_recycle=config.db_pool_recycle,
            pool_timeout=config.db_pool_timeout,
        )
    else:
        server.use_in_memory_repositories()

    # 加载插件（按 UMCP_PLUGINS 逗号分隔顺序）
    plugins_env = os.environ.get("UMCP_PLUGINS", "").strip()
    if plugins_env:
        for name in [p.strip() for p in plugins_env.split(",") if p.strip()]:
            try:
                server.load_plugin(name)
                print(f"[UMCP] 已加载插件: {name}", file=sys.stderr)
            except Exception as e:
                print(f"[UMCP] 加载插件 {name} 失败: {e}", file=sys.stderr)

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
