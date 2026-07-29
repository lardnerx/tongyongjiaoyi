"""Transport 配置：环境变量加载。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(var_name: str, default: int) -> int:
    """从环境变量读取整数，转换失败时抛出包含变量名的 ValueError。"""
    raw = os.getenv(var_name, str(default))
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"环境变量 {var_name} 必须为整数，当前值: {raw!r}") from e


@dataclass
class TransportConfig:
    """传输层配置。"""

    jwt_secret: str
    jwt_access_ttl: int = 3600
    jwt_refresh_ttl: int = 604800
    db_dsn: str | None = None
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "TransportConfig":
        secret = os.getenv("UMCP_JWT_SECRET")
        if not secret:
            raise ValueError("UMCP_JWT_SECRET 环境变量必填")

        dsn = os.getenv("UMCP_DB_DSN")
        cors_raw = os.getenv("UMCP_CORS_ORIGINS", "*")
        cors_origins = [s.strip() for s in cors_raw.split(",") if s.strip()]

        return cls(
            jwt_secret=secret,
            jwt_access_ttl=_env_int("UMCP_JWT_ACCESS_TTL", 3600),
            jwt_refresh_ttl=_env_int("UMCP_JWT_REFRESH_TTL", 604800),
            db_dsn=dsn,
            cors_origins=cors_origins,
            log_level=os.getenv("UMCP_LOG_LEVEL", "INFO"),
            host=os.getenv("UMCP_HOST", "0.0.0.0"),
            port=_env_int("UMCP_PORT", 8000),
        )
