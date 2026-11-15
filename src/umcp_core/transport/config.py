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
    # DB 连接池参数
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600
    db_pool_timeout: int = 30
    # 认证缓存策略（灰度测试用）
    auth_cache_ttl: int = 60
    # 严格认证模式：禁止自动建号、强制密码登录、关闭免验证重置密码（生产必须为 True）
    auth_strict: bool = True
    # 支付网关配置（为空则使用 Mock 网关）
    wechat_app_id: str = ""
    wechat_mch_id: str = ""
    wechat_api_v3_key: str = ""
    wechat_mch_serial_no: str = ""
    wechat_private_key_path: str = ""
    wechat_notify_url: str = ""
    # 限流配置
    rate_limit_enabled: bool = False
    rate_limit_window_seconds: int = 60
    rate_limit_max_requests: int = 100
    rate_limit_redis_url: str = "redis://localhost:6379/0"
    # 短信通知配置（互亿无线，默认）
    sms_api_id: str = ""
    sms_api_key: str = ""
    sms_sign: str = ""
    # 短信通知配置（阿里云，备选）
    sms_access_key_id: str = ""
    sms_access_key_secret: str = ""
    sms_sign_name: str = ""
    sms_template_code: str = ""

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
            db_pool_size=_env_int("UMCP_DB_POOL_SIZE", 10),
            db_max_overflow=_env_int("UMCP_DB_MAX_OVERFLOW", 20),
            db_pool_recycle=_env_int("UMCP_DB_POOL_RECYCLE", 3600),
            db_pool_timeout=_env_int("UMCP_DB_POOL_TIMEOUT", 30),
            auth_cache_ttl=_env_int("UMCP_AUTH_CACHE_TTL", 60),
            auth_strict=os.getenv("UMCP_AUTH_STRICT", "true").strip().lower() != "false",
            # 微信支付配置
            wechat_app_id=os.getenv("WECHAT_APP_ID", ""),
            wechat_mch_id=os.getenv("WECHAT_MCH_ID", ""),
            wechat_api_v3_key=os.getenv("WECHAT_API_V3_KEY", ""),
            wechat_mch_serial_no=os.getenv("WECHAT_MCH_SERIAL_NO", ""),
            wechat_private_key_path=os.getenv("WECHAT_PRIVATE_KEY_PATH", ""),
            wechat_notify_url=os.getenv("WECHAT_NOTIFY_URL", ""),
            # 限流配置
            rate_limit_enabled=os.getenv("UMCP_RATE_LIMIT_ENABLED", "false").lower() == "true",
            rate_limit_window_seconds=_env_int("UMCP_RATE_LIMIT_WINDOW", 60),
            rate_limit_max_requests=_env_int("UMCP_RATE_LIMIT_MAX", 100),
            rate_limit_redis_url=os.getenv("UMCP_RATE_LIMIT_REDIS_URL", "redis://localhost:6379/0"),
            # 短信通知配置（互亿无线，默认）
            sms_api_id=os.getenv("IHUYI_SMS_API_ID", ""),
            sms_api_key=os.getenv("IHUYI_SMS_API_KEY", ""),
            sms_sign=os.getenv("IHUYI_SMS_SIGN", ""),
            # 短信通知配置（阿里云，备选）
            sms_access_key_id=os.getenv("ALIYUN_SMS_ACCESS_KEY_ID", ""),
            sms_access_key_secret=os.getenv("ALIYUN_SMS_ACCESS_KEY_SECRET", ""),
            sms_sign_name=os.getenv("ALIYUN_SMS_SIGN_NAME", ""),
            sms_template_code=os.getenv("ALIYUN_SMS_TEMPLATE_CODE", ""),
        )

    @property
    def has_wechat_config(self) -> bool:
        """检查是否配置了完整的微信支付参数。"""
        return bool(
            self.wechat_app_id
            and self.wechat_mch_id
            and self.wechat_api_v3_key
            and self.wechat_mch_serial_no
            and self.wechat_private_key_path
        )
