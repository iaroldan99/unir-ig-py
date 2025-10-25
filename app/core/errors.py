import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):  # pragma: no cover
        logger.warning("AppError: %s", exc.message)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_: Request, exc: ValidationError):  # pragma: no cover
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException):  # pragma: no cover
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


