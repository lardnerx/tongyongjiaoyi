"""基于 Redis 的滑动窗口限流中间件（带内存降级模式）。

防止支付回调接口在高频请求下出现并发问题。
支持：
  - 滑动窗口算法，精确控制单位时间内的请求数
  - 豁免路径（如支付回调本身可配置为不受限）
  - 自定义窗口大小和最大请求数
  - Redis 连接池配置，支持生产环境参数调优
  - 健康检查与自动降级（Redis 不可用时自动切换到内存模式）
  - 内存降级模式（无 Redis 时仍可限流，限同一进程内）

环境变量配置：
  UMCP_RATE_LIMIT_ENABLED     — 是否启用限流（默认 false）
  UMCP_RATE_LIMIT_WINDOW      — 时间窗口（秒，默认 60）
  UMCP_RATE_LIMIT_MAX         — 窗口内最大请求数（默认 100）
  UMCP_RATE_LIMIT_REDIS_URL   — Redis 连接地址（默认 redis://localhost:6379/0）
"""

from __future__ import annotations

import logging
import time
import re
import threading
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Redis 连接池默认参数
_DEFAULT_POOL_SIZE = 20
_DEFAULT_CONNECT_TIMEOUT = 5
_DEFAULT_SOCKET_TIMEOUT = 5
_DEFAULT_HEALTH_CHECK_INTERVAL = 15
_HEALTH_CHECK_PERIOD = 30.0  # 每 30 秒检查一次 Redis 健康状态


def _mask_redis_password(url: str) -> str:
    """脱敏 Redis URL 中的密码，避免日志泄露。"""
    return re.sub(r"(redis://[^:]*:)([^@]+)(@.*)", r"\1****\3", url)


class _InMemorySlidingWindow:
    """内存滑动窗口（线程安全）。

    当 Redis 不可用时作为降级方案使用。
    每个客户端维护一个请求时间戳列表，在窗口内滑动。
    """

    def __init__(self, window_seconds: int) -> None:
        self._window_seconds = window_seconds
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str, max_requests: int) -> bool:
        """检查是否允许请求，并记录本次请求。"""
        now = time.time()
        window_start = now - self._window_seconds

        with self._lock:
            timestamps = self._windows[key]
            # 移除窗口外的记录
            while timestamps and timestamps[0] < window_start:
                timestamps.pop(0)
            # 检查是否超过限制
            if len(timestamps) >= max_requests:
                return False
            # 记录当前请求
            timestamps.append(now)
            return True

    def cleanup(self) -> None:
        """清理过期条目，防止内存泄漏。"""
        now = time.time()
        window_start = now - self._window_seconds * 2
        with self._lock:
            expired_keys = [k for k, v in self._windows.items() if not v or v[-1] < window_start]
            for k in expired_keys:
                del self._windows[k]


class RateLimitExceeded(Exception):
    """限流触发异常。"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于 Redis 有序集合（Sorted Set）的滑动窗口限流中间件。

    每个客户端（按 IP）维护一个有序集合，以请求时间戳为 score，
    每次请求时移除窗口外的记录，若窗口内记录数超过阈值则返回 429。

    生产环境适配：
      - 连接池：通过 redis_url 参数中的 max_connections 控制
      - 超时：socket_connect_timeout 和 socket_timeout 可配置
      - 降级：Redis 异常时自动切换到内存模式，仍可限流
    """

    _MODE_REDIS = "redis"
    _MODE_MEMORY = "memory"

    def __init__(
        self,
        app,
        window_seconds: int = 60,
        max_requests: int = 100,
        redis_url: str = "redis://localhost:6379/0",
        exempt_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._window_seconds = window_seconds
        self._max_requests = max_requests
        self._redis_url = redis_url
        self._exempt_paths = exempt_paths or []
        self._redis = None  # 延迟初始化
        self._mode = self._MODE_REDIS  # 当前模式
        self._redis_healthy = True  # Redis 健康状态标记
        self._last_health_check = 0.0

        # 内存降级模式滑动窗口
        self._memory_window = _InMemorySlidingWindow(window_seconds)
        # 定期清理内存窗口过期条目（每 5 分钟）
        self._last_cleanup = 0.0

        logger.info(
            "[RATE_LIMIT_INIT] window=%ss max=%s redis_url=%s exempt_paths=%s",
            window_seconds, max_requests,
            _mask_redis_password(redis_url),
            exempt_paths,
        )

    async def _get_redis(self):
        """延迟初始化 Redis 连接池。

        生产环境通过 redis_url 传入连接池参数，例如：
          redis://:password@host:6379/0?max_connections=50&socket_connect_timeout=5&socket_timeout=5
        """
        if self._redis is None:
            import redis.asyncio as aioredis
            url = self._redis_url
            # 如果 URL 中没有显式设置超时参数，使用默认值
            if "socket_connect_timeout" not in url:
                url += "&socket_connect_timeout=5" if "?" in url else "?socket_connect_timeout=5"
            if "socket_timeout" not in url:
                url += "&socket_timeout=5"
            if "max_connections" not in url:
                url += "&max_connections=20"
            self._redis = aioredis.from_url(
                url,
                decode_responses=True,
                retry_on_timeout=True,
                health_check_interval=15,
            )
            logger.info(
                "[RATE_LIMIT] Redis 连接池已初始化: url=%s",
                _mask_redis_password(self._redis_url),
            )
        return self._redis

    async def _check_redis_health(self) -> bool:
        """检查 Redis 连接健康状态，避免频繁检查。"""
        now = time.time()
        if now - self._last_health_check < _HEALTH_CHECK_PERIOD:
            return self._redis_healthy
        self._last_health_check = now
        try:
            redis_conn = await self._get_redis()
            await redis_conn.ping()
            if not self._redis_healthy:
                logger.info("[RATE_LIMIT] Redis 连接已恢复，切回 Redis 模式")
                self._mode = self._MODE_REDIS
            self._redis_healthy = True
        except Exception as e:
            if self._redis_healthy:
                logger.warning(
                    "[RATE_LIMIT] Redis 不可用，切换到内存降级模式: %s", e,
                )
                self._mode = self._MODE_MEMORY
            self._redis_healthy = False
        return self._redis_healthy

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # 豁免路径直接放行
        if path in self._exempt_paths:
            return await call_next(request)

        # 获取客户端标识（优先使用 X-Forwarded-For，其次直连 IP）
        forwarded = request.headers.get("X-Forwarded-For", "")
        client_id = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (request.client.host if request.client else "unknown")
        )

        now = time.time()
        key = f"rate_limit:{client_id}"

        # 检查 Redis 健康状态（无 Redis 时自动切换到内存模式）
        if self._mode == self._MODE_REDIS:
            await self._check_redis_health()

        if self._mode == self._MODE_REDIS:
            # ---- Redis 模式 ----
            limited = await self._check_redis_limit(key, client_id, path)
        else:
            # ---- 内存降级模式 ----
            limited = self._check_memory_limit(key, client_id, path)
            # 定期清理内存窗口（每 60 秒）
            if now - self._last_cleanup > 60:
                self._memory_window.cleanup()
                self._last_cleanup = now

        if limited:
            return Response(
                status_code=429,
                content=(
                    '{'
                    '"error":"rate_limit_exceeded",'
                    '"message":"请求过于频繁，请稍后再试",'
                    f'"retry_after":{self._window_seconds}'
                    '}'
                ),
                media_type="application/json",
                headers={"Retry-After": str(self._window_seconds)},
            )

        return await call_next(request)

    async def _check_redis_limit(self, key: str, client_id: str, path: str) -> bool:
        """使用 Redis 检查限流。"""
        now = int(time.time())
        try:
            redis_conn = await self._get_redis()
            pipeline = redis_conn.pipeline()

            # 1. 移除窗口外的请求记录
            pipeline.zremrangebyscore(key, 0, now - self._window_seconds)
            # 2. 添加当前请求时间戳
            pipeline.zadd(key, {str(now): now})
            # 3. 设置键过期时间（防止内存泄漏）
            pipeline.expire(key, self._window_seconds * 2)
            # 4. 统计窗口内请求数
            pipeline.zcard(key)

            results = await pipeline.execute()
            request_count = results[-1]  # zcard 的结果

            if request_count > self._max_requests:
                logger.warning(
                    "[RATE_LIMIT] exceeded: client=%s path=%s count=%s max=%s window=%ss",
                    client_id, path, request_count, self._max_requests, self._window_seconds,
                )
                return True

            logger.debug(
                "[RATE_LIMIT] ok: client=%s path=%s count=%s/%s",
                client_id, path, request_count, self._max_requests,
            )
        except Exception as e:
            # Redis 异常时切换到内存模式
            logger.warning(
                "[RATE_LIMIT] redis unavailable, switching to memory mode: %s", e,
            )
            self._mode = self._MODE_MEMORY
            self._redis_healthy = False
            # 使用内存模式检查本次请求
            return self._check_memory_limit(key, client_id, path)

        return False

    def _check_memory_limit(self, key: str, client_id: str, path: str) -> bool:
        """使用内存滑动窗口检查限流。"""
        allowed = self._memory_window.is_allowed(key, self._max_requests)
        if not allowed:
            logger.warning(
                "[RATE_LIMIT(memory)] exceeded: client=%s path=%s max=%s window=%ss",
                client_id, path, self._max_requests, self._window_seconds,
            )
            return True

        logger.debug(
            "[RATE_LIMIT(memory)] ok: client=%s path=%s max=%s",
            client_id, path, self._max_requests,
        )
        return False