"""Application factory."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .api import infra
from .api.v1.router import api_router
from .config import Settings, get_settings
from .core.errors import install_error_handlers
from .core.middleware import RequestContextMiddleware
from .core.readiness import ReadinessRegistry, storage_writable_check


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    readiness = ReadinessRegistry()
    readiness.register("storage", storage_writable_check(settings.data_root))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        yield

    app = FastAPI(
        title="Gridora API",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url=None if settings.env == "prod" else "/api/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.readiness = readiness

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(infra.router)
    app.include_router(api_router)
    return app


def run() -> FastAPI:  # uvicorn --factory gridora_api.main:run
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
