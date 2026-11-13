"""All runtime configuration lives here (environment variables, prefix GRIDORA_)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from gridora_contracts.models import MAX_UPLOAD_BYTES, MAX_WINDOW_COLS, MAX_WINDOW_ROWS
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRIDORA_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://gridora:gridora@localhost:5432/gridora"
    data_root: Path = Path("./data")

    # Cookies are Secure by default; disabling is an explicit dev-only decision.
    secure_cookies: bool = True

    # Which implementation composition/ wires in. "stub" is the in-memory CSV-only stand-in.
    engine: Literal["stub", "real"] = "stub"
    dataops: Literal["stub", "real"] = "stub"

    # The contract caps are upper bounds; they can only be lowered here.
    max_upload_bytes: int = Field(default=MAX_UPLOAD_BYTES, ge=1, le=MAX_UPLOAD_BYTES)
    max_window_rows: int = Field(default=MAX_WINDOW_ROWS, ge=1, le=MAX_WINDOW_ROWS)
    max_window_cols: int = Field(default=MAX_WINDOW_COLS, ge=1, le=MAX_WINDOW_COLS)

    @model_validator(mode="after")
    def _prod_requires_secure_cookies(self) -> Settings:
        if self.env == "prod" and not self.secure_cookies:
            raise ValueError("secure_cookies must be true when GRIDORA_ENV=prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
