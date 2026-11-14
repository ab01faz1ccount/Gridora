"""All /api/v1 routers are included here. PR 1 mounts none: routes arrive with their PRs."""
from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
