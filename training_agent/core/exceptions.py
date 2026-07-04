from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse


class AppException(Exception):
    def __init__(self, message: str, code: int = 1):
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, code=404)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, code=401)


class ForbiddenException(AppException):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, code=403)


class ValidationException(AppException):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, code=422)


class ExternalServiceException(AppException):
    def __init__(self, message: str = "External service error"):
        super().__init__(message, code=502)


def app_exception_handler(request: Any, exc: AppException):
    from fastapi.responses import JSONResponse
    from fastapi import Request

    return JSONResponse(
        status_code=exc.code,
        content={"code": exc.code, "data": None, "msg": exc.message},
    )