"""Settings, read from environment variables and backend/.env (env vars win).

Every variable is documented in backend/.env.example.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"

Environment = Literal["dev", "test", "staging", "prod"]
# Placeholder secrets in .env.example start with this; staging/prod refuse them.
DEV_SECRET_PREFIX = "dev-only-"
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

    # Supabase Auth. Without SUPABASE_URL, user endpoints answer 503 auth_not_configured
    # (required in staging/prod).
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    # Used only by scripts/dev_login.py; the API never needs it.
    supabase_publishable_key: str | None = None
    jwks_cache_seconds: float = Field(default=600.0, gt=0)
    jwks_min_refresh_interval_seconds: float = Field(default=30.0, ge=0)
    jwt_leeway_seconds: float = Field(default=30.0, ge=0)

    # HMAC key for invite and pairing codes (a leaked DB alone can't brute-force live codes).
    code_hash_secret: SecretStr = Field(min_length=32)
    invite_ttl_hours: float = Field(default=48.0, gt=0)
    pairing_code_ttl_minutes: float = Field(default=15.0, gt=0)
    invite_link_base_url: str = "nodly://invite/"
    pairing_qr_base_url: str = "nodly://pair/"

    # Brute-force protection for code guessing (pairing claims, invite preview/accept).
    throttle_window_seconds: int = Field(default=900, ge=1)
    throttle_max_failures_per_ip: int = Field(default=10, ge=1)
    throttle_max_failures_per_user: int = Field(default=10, ge=1)
    throttle_max_failures_global: int = Field(default=500, ge=1)
    throttle_max_pin_failures_per_device: int = Field(default=5, ge=1)

    device_token_rotation_grace_seconds: float = Field(default=600.0, ge=0)
    device_last_seen_interval_seconds: float = Field(default=300.0, ge=0)

    # Push. "expo" sends through the Expo Push Service; "record" only keeps messages in memory
    # (tests, or offline dev). The access token is needed only if "enhanced security" is on
    # for the Expo project.
    push_provider: Literal["expo", "record"] = "expo"
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    expo_push_access_token: SecretStr | None = None

    # The check-in engine's tick (CLAUDE.md §7).
    checkin_tick_seconds: float = Field(default=60.0, gt=0)

    @property
    def supabase_issuer(self) -> str | None:
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else None

    @property
    def supabase_jwks_url(self) -> str | None:
        issuer = self.supabase_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else None

    @model_validator(mode="after")
    def _check_job_timeouts(self) -> Self:
        # A job still running when its lock expires would be reclaimed and run twice.
        if self.job_lock_timeout_seconds <= self.job_timeout_seconds:
            raise ValueError("JOB_LOCK_TIMEOUT_SECONDS must be greater than JOB_TIMEOUT_SECONDS")
        if self.job_backoff_max_seconds < self.job_backoff_base_seconds:
            raise ValueError("JOB_BACKOFF_MAX_SECONDS must be >= JOB_BACKOFF_BASE_SECONDS")
        return self

    @model_validator(mode="after")
    def _check_deployed_secrets(self) -> Self:
        if self.env in ("staging", "prod"):
            if not self.supabase_url:
                raise ValueError("SUPABASE_URL is required in staging and prod")
            if self.code_hash_secret.get_secret_value().startswith(DEV_SECRET_PREFIX):
                raise ValueError("CODE_HASH_SECRET must be a real secret in staging and prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required values come from the environment
