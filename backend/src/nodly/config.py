"""Settings, read from environment variables and backend/.env (env vars win).

Every variable is documented in backend/.env.example.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"

Environment = Literal["dev", "test", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    # An absolute path, so the API, worker, Alembic and tests find the same file from any folder.
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # No default on purpose: dev-only routes are mounted when ENV=dev, so it must be explicit.
    env: Environment

    database_url: str
    test_database_url: str | None = None
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_echo: bool = False

    log_level: LogLevel = "INFO"
    log_format: Literal["json", "console"] = "json"

    readiness_db_timeout_seconds: float = Field(default=2.0, gt=0)

    worker_poll_interval_seconds: float = Field(default=1.0, gt=0)
    worker_concurrency: int = Field(default=4, ge=1)
    worker_shutdown_grace_seconds: float = Field(default=30.0, ge=0)

    job_default_max_attempts: int = Field(default=5, ge=1)
    job_backoff_base_seconds: float = Field(default=10.0, gt=0)
    job_backoff_max_seconds: float = Field(default=3600.0, gt=0)
    job_timeout_seconds: float = Field(default=300.0, gt=0)
    job_lock_timeout_seconds: float = Field(default=900.0, gt=0)

    @model_validator(mode="after")
    def _check_job_timeouts(self) -> Self:
        # A job still running when its lock expires would be reclaimed and run twice.
        if self.job_lock_timeout_seconds <= self.job_timeout_seconds:
            raise ValueError("JOB_LOCK_TIMEOUT_SECONDS must be greater than JOB_TIMEOUT_SECONDS")
        if self.job_backoff_max_seconds < self.job_backoff_base_seconds:
            raise ValueError("JOB_BACKOFF_MAX_SECONDS must be >= JOB_BACKOFF_BASE_SECONDS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required values come from the environment
