"""All /api/v1 routers are included here."""

from __future__ import annotations

from fastapi import APIRouter

from . import auth, jobs, workbooks, workspaces

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(jobs.router)
api_router.include_router(workbooks.router)
