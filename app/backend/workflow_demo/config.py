"""Runtime configuration, read from environment variables (or a local ``.env``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Access
    demo_passcode: SecretStr
    admin_passcode: SecretStr
    session_secret: SecretStr
    max_users: int = 10
    session_days: int = 7
    admin_session_hours: int = 12

    # Deployments
    deployment_ttl_hours: int = 24
    fake_platforms: bool = Field(default=False, validation_alias="DEMO_FAKE_PLATFORMS")

    # Infrastructure
    database_url: str = "sqlite:///./workflow_demo.db"
    public_base_url: str = "http://localhost:8000"
    cookie_secure: bool = True

    @property
    def base_url(self) -> str:
        return self.public_base_url.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
