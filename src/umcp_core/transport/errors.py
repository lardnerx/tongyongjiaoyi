"""API 错误体系：统一错误码 + HTTP 状态映射。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """业务错误基类，携带 code 和 HTTP status。"""

    def __init__(
        self,
        code: int,
        message: str = "",
        status: int = 400,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


# 1xxx 认证类
class InvalidCredentialError(ApiError):
    def __init__(self, code: int = 1001, message: str = "无效凭据", status: int = 401, details: Any = None) -> None:
        super().__init__(code, message, status, details)


class TokenExpiredError(ApiError):
    def __init__(self, code: int = 1002, message: str = "token 已过期", status: int = 401, details: Any = None) -> None:
        super().__init__(code, message, status, details)


class PermissionDeniedError(ApiError):
    def __init__(self, code: int = 1003, message: str = "权限不足", status: int = 403, details: Any = None) -> None:
        super().__init__(code, message, status, details)


# 2xxx 资源类
class NotFoundError(ApiError):
    def __init__(self, code: int = 2001, message: str = "资源不存在", status: int = 404, details: Any = None) -> None:
        super().__init__(code, message, status, details)


class IllegalStateError(ApiError):
    def __init__(self, code: int = 2002, message: str = "状态非法", status: int = 409, details: Any = None) -> None:
        super().__init__(code, message, status, details)


class ValidationError(ApiError):
    def __init__(self, code: int = 2003, message: str = "参数校验失败", status: int = 422, details: Any = None) -> None:
        super().__init__(code, message, status, details)


# 3xxx 业务类
class MatchFailedError(ApiError):
    def __init__(self, code: int = 3001, message: str = "匹配失败", status: int = 422, details: Any = None) -> None:
        super().__init__(code, message, status, details)


class PaymentFailedError(ApiError):
    def __init__(self, code: int = 3002, message: str = "支付失败", status: int = 422, details: Any = None) -> None:
        super().__init__(code, message, status, details)


def register_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理器。"""

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": 2003,
                "message": "参数校验失败",
                "details": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unknown(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"code": 5000, "message": "服务器内部错误"},
        )
