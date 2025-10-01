from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration pulled from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="", env_file=(".env", ".env.local"), extra="ignore"
    )

    app_name: str = Field(default="CostCourter")
    environment: Literal["local", "staging", "production", "test"] = Field(
        default="local"
    )
    debug: bool = Field(default=True)
    base_url: str = Field(default="http://localhost:8000")
    timezone: str = Field(default="UTC")

    postgres_host: str = Field(default="127.0.0.1")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="costcourter")
    postgres_user: str = Field(default="costcourter")
    postgres_password: str = Field(default="costcourter")

    redis_host: str = Field(default="127.0.0.1")
    redis_port: int = Field(default=6379)
    redis_username: str | None = Field(default=None)
    redis_password: str | None = Field(default=None)
    redis_db: int = Field(default=0)
    redis_pool_max_connections: int = Field(default=200, ge=1)

    jwt_secret_key: str = Field(default="change-me", min_length=8)
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30)

    searxng_url: str | None = Field(default=None)
    scraper_base_url: str | None = Field(default=None)
    scraper_request_timeout: float = Field(default=30.0, ge=0.0)
    scraper_connect_timeout: float = Field(default=30.0, ge=0.0)
    price_fetch_chunk_size: int = Field(default=25, ge=1)

    smtp_host: str | None = Field(default=None)
    smtp_port: int | None = Field(default=None)
    smtp_username: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_from_address: str | None = Field(default=None)
    smtp_from_name: str | None = Field(default=None)

    oidc_client_id: str | None = Field(default=None)
    oidc_client_secret: str | None = Field(default=None)
    oidc_authorization_endpoint: AnyHttpUrl | None = Field(default=None)
    oidc_token_endpoint: AnyHttpUrl | None = Field(default=None)
    oidc_userinfo_endpoint: AnyHttpUrl | None = Field(default=None)
    oidc_redirect_uri: AnyHttpUrl | None = Field(default=None)
    oidc_issuer: AnyHttpUrl | None = Field(default=None)
    oidc_scopes: list[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"]
    )
    oidc_state_ttl_seconds: int = Field(default=300)

    passkey_relying_party_id: str | None = Field(default=None)
    passkey_relying_party_name: str | None = Field(default=None)
    passkey_origin: AnyHttpUrl | None = Field(default=None)
    passkey_challenge_ttl_seconds: int = Field(default=300)
    passkey_timeout_ms: int = Field(default=60000)
    passkey_require_user_verification: bool = Field(default=True)

    notify_email_enabled: bool = Field(default=False)
    notify_pushover_token: str | None = Field(default=None)
    notify_pushover_user: str | None = Field(default=None)
    notify_gotify_url: AnyHttpUrl | None = Field(default=None)
    notify_gotify_token: str | None = Field(default=None)
    apprise_config_path: str | None = Field(default=None)

    celery_beat_schedule_path: str | None = Field(default=None)
    celery_worker_concurrency: int = Field(default=1, ge=1)
    celery_schedule_alert_multiplier: float = Field(default=1.5, ge=1.0)
    celery_schedule_alert_min_grace_minutes: int = Field(default=30, ge=0)

    search_cache_ttl_seconds: int = Field(default=600, ge=1)
    audit_log_purge_days: int = Field(default=90, ge=1)

    cors_origins: list[str] = Field(default_factory=list)

    @property
    def database_uri(self) -> str:
        """Return a SQLAlchemy-compatible database URI."""

        user = self.postgres_user
        password = self.postgres_password
        host = self.postgres_host
        port = self.postgres_port
        db = self.postgres_db
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"

    @property
    def redis_uri(self) -> str:
        """Return a Redis URI suitable for Celery or cache configuration."""

        auth = ""
        if self.redis_username and self.redis_password:
            auth = f"{self.redis_username}:{self.redis_password}@"
        elif self.redis_password:
            auth = f":{self.redis_password}@"
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
