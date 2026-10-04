"""Runtime configuration, read from environment variables (or a local ``.env``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Just the database URL; used by Alembic, which doesn't need the rest."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite:///./workflow_demo.db"


class Settings(BaseSettings):
    # Empty values (``KEY=`` lines in .env.example) count as unset.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Access
    demo_passcode: SecretStr
    admin_passcode: SecretStr
    session_secret: SecretStr
    max_users: int = 10
    session_days: int = 7
    admin_session_hours: int = 12

    # Deployments
    deployment_ttl_hours: float = 24  # a fraction (e.g. 0.05) is handy for a live expiry test
    sweep_interval_seconds: int = 600  # 0 turns the background sweeper off
    # Delete demo items on n8n/Make that no deployment references. Only for the one instance that
    # owns the platform accounts: another instance (e.g. a local run with the same keys) would see
    # the hosted demo's items as unreferenced.
    orphan_sweep: bool = False
    fake_platforms: bool = Field(default=False, validation_alias="DEMO_FAKE_PLATFORMS")
    # Jobs run inside this process, so on startup any unfinished job was lost: fail it.
    recover_jobs_on_startup: bool = True
    # Comma-separated workflow IDs switched off on this server (shown with the catalog's unavailable_note).
    disabled_workflows: str = ""

    # Connections
    nango_secret_key: SecretStr | None = None
    nango_host: str = "https://api.nango.dev"
    nango_connect_url: str = "https://connect.nango.dev"  # Connect UI (only differs when self-hosting)
    # 32 random bytes, base64 (python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
    data_encryption_key: SecretStr | None = None

    # n8n (uptime monitor, Meegle digest, Medium digest)
    n8n_base_url: str | None = None  # e.g. https://acme.app.n8n.cloud
    n8n_api_key: SecretStr | None = None
    # The Internal Google OAuth client configured in Nango; n8n needs it to refresh Google tokens.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # Owner-provided keys, given to each Medium digest deployment as its own n8n credentials.
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    reader_base_url: str | None = None  # the medium-reader service (P4)
    reader_api_token: SecretStr | None = None

    # Make Bridge (GitHub merge → Slack, P5); see catalog/github-merge-slack/make-setup.md
    make_zone: str = "us2.make.com"
    make_team_id: int | None = None
    make_bridge_key_id: str | None = None
    make_bridge_secret: SecretStr | None = None
    make_bridge_template_id: int | None = None

    # Shared Slack → Meegle bot on Modal (P4): it calls /api/bot/* with this token.
    bot_api_token: SecretStr | None = None
    # Optional: the bot's Slack workspace; testers must connect Slack in the same one.
    slack_bot_team_id: str | None = None

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
