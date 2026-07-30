"""Prometheus 指标定义与 HTTP middleware。"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# 指标定义
http_requests_total = Counter(
    "http_requests_total",
    "HTTP 请求总数",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求处理耗时（秒）",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求的计数与耗时。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # /metrics 自身不记录，避免自激
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # 用路由路径模板（如 /api/v1/deals/{deal_id}）避免高基数
        route = request.scope.get("route")
        path_template = getattr(route, "path", request.url.path) if route else request.url.path

        http_requests_total.labels(
            method=request.method,
            path=path_template,
            status=str(response.status_code),
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            path=path_template,
        ).observe(duration)

        return response


def metrics_response() -> Response:
    """返回 /metrics 端点的 Prometheus 文本。"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
