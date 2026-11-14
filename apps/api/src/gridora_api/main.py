"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from . import __version__
from .api import infra
from .api.v1.router import api_router
from .composition.wiring import build_services
from .config import Settings, get_settings
from .core.errors import install_error_handlers
from .core.middleware import RequestContextMiddleware
from .core.ratelimit import LoginLimiter
from .core.readiness import ReadinessRegistry, storage_writable_check
from .db.session import make_engine, make_sessionmaker
from .services import auth as auth_service
from .services.passwords import Hasher
from .storage.layout import StorageLayout


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    readiness = ReadinessRegistry()
    readiness.register("storage", storage_writable_check(settings.data_root))
    engine = make_engine(settings)
    sessionmaker = make_sessionmaker(engine)
    hasher = Hasher(settings)
    layout = StorageLayout(settings.data_root)
    services = build_services(settings, layout)  # fails fast if a configured module is missing

    async def db_check() -> bool:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True

    readiness.register("db", db_check)

    async def impl_check() -> bool:
        return True  # build_services() already validated both implementations at startup

    readiness.register("composition", impl_check)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        layout.ensure_dirs()
        try:
            async with sessionmaker() as db:
                if await auth_service.bootstrap_admin(db, settings, hasher):
                    logging.getLogger("gridora").warning(
                        "bootstrap admin created; remove GRIDORA_BOOTSTRAP_ADMIN_* from env"
                    )
        except Exception:  # noqa: BLE001 - DB may be starting; /readyz reports it
            logging.getLogger("gridora").exception("bootstrap admin step failed")
        try:
            yield
        finally:
            await engine.dispose()

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
    app.state.sessionmaker = sessionmaker
    app.state.hasher = hasher
    app.state.layout = layout
    app.state.services = services
    app.state.implementations = {"engine": services.engine_kind, "dataops": services.dataops_kind}
    app.state.limiter = LoginLimiter(
        settings.login_window_seconds,
        settings.login_max_failures_per_user,
        settings.login_max_failures_per_ip,
    )

    install_error_handlers(app)
    app.add_middleware(
        RequestContextMiddleware,
        extra_headers={
            "X-Gridora-Engine": services.engine_kind,
            "X-Gridora-Dataops": services.dataops_kind,
        },
    )
    app.include_router(infra.router)
    app.include_router(api_router)
    return app


def run() -> FastAPI:  # uvicorn --factory gridora_api.main:run
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
