"""All runtime configuration lives here (environment variables, prefix GRIDORA_)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from gridora_contracts.models import MAX_UPLOAD_BYTES, MAX_WINDOW_COLS, MAX_WINDOW_ROWS
from pydantic import Field, SecretStr, model_validator
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

    # Sessions (server-side). Idle timeout slides; the absolute lifetime does not.
    session_idle_seconds: int = Field(default=8 * 3600, ge=60)
    session_absolute_seconds: int = Field(default=7 * 24 * 3600, ge=60)
    trust_proxy_headers: bool = False  # true only behind our nginx (uses X-Real-IP)

    # Login rate limiting (Postgres-backed).
    login_window_seconds: int = Field(default=900, ge=1)
    login_max_failures_per_user: int = Field(default=5, ge=1)
    login_max_failures_per_ip: int = Field(default=30, ge=1)

    # argon2id parameters (argon2-cffi defaults follow RFC 9106 low-memory profile).
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_memory_cost_kib: int = Field(default=65536, ge=8)
    argon2_parallelism: int = Field(default=4, ge=1)

    # First-start bootstrap (only used when there are no users). Remove after first start.
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None

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
